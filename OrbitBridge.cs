using System;
using System.IO;
using System.Diagnostics;
using System.Globalization;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Threading;
using System.Net;
using System.Net.Sockets;

// Experimental interoperability diagnostic for the exact DLL inspected.
// No firmware, EEPROM or settings changes. UDP output is loopback only.
// The only data write is the user-approved meter-refresh flag (host word 11=1).
// Register reads internally issue address-selection USB commands via the vendor
// DLL; this is not a passive USB capture. Tested on one Cloud Orbit S setup;
// wider hardware/firmware compatibility has not been established.
class OrbitSensorTest
{
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern IntPtr LoadLibraryEx(string name, IntPtr file, uint flags);
    [DllImport("kernel32.dll", CharSet=CharSet.Ansi, ExactSpelling=true)]
    static extern IntPtr GetProcAddress(IntPtr module, string name);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int Init(int mode, uint flags);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate uint Open(uint vid, uint pid);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int Close(uint handle);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int Uninit(uint unused);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int ReadDsp(byte slave, uint address, out uint value, uint length);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)]
    delegate int WriteDsp(byte slave, uint address, uint value, uint length);
    static StreamWriter log;
    static ReadDsp read;
    static volatile bool cancel;
    static long progressTicks = Stopwatch.GetTimestamp();
    static readonly object logLock = new object();
    static double[] Multiply(double[] a, double[] b)
    {
        return new double[] {
            a[0]*b[0]-a[1]*b[1]-a[2]*b[2]-a[3]*b[3],
            a[0]*b[1]+a[1]*b[0]+a[2]*b[3]-a[3]*b[2],
            a[0]*b[2]-a[1]*b[3]+a[2]*b[0]+a[3]*b[1],
            a[0]*b[3]+a[1]*b[2]-a[2]*b[1]+a[3]*b[0] };
    }
    static double[] Angles(double[] q, double[] center)
    {
        double[] r = Multiply(new double[]{center[0],-center[1],-center[2],-center[3]},q);
        double w=r[0],x=r[1],y=r[2],z=r[3], deg=180.0/Math.PI;
        return new double[] {
            Math.Atan2(2*(w*y+x*z),1-2*(x*x+y*y))*deg,
            Math.Asin(Math.Max(-1,Math.Min(1,2*(w*x-y*z))))*deg,
            Math.Atan2(2*(w*z+x*y),1-2*(x*x+z*z))*deg };
    }
    static byte[] Packet(double[] angles)
    {
        // OpenTrack UDP: six little-endian doubles, x,y,z,yaw,pitch,roll.
        byte[] packet = new byte[48];
        for(int i=0;i<3;i++) {
            byte[] bytes=BitConverter.GetBytes(angles[i]);
            if(!BitConverter.IsLittleEndian) Array.Reverse(bytes);
            Buffer.BlockCopy(bytes,0,packet,24+i*8,8);
        }
        return packet;
    }

    static void Say(string message)
    {
        lock(logLock) { Console.WriteLine(message); if(log != null) log.WriteLine(message); }
    }
    static T Function<T>(IntPtr module, string name) where T : class
    {
        IntPtr p = GetProcAddress(module, name);
        if(p == IntPtr.Zero) throw new Exception("Missing DLL function: " + name);
        return Marshal.GetDelegateForFunctionPointer(p, typeof(T)) as T;
    }
    static uint Read(uint address)
    {
        uint value;
        if(read(0x5a, address, out value, 4) == 0)
            throw new Exception("Read failed at " + address.ToString("X8"));
        return value;
    }
    static void CheckPointer(uint address)
    {
        // Do not infer data placement from the address of a pointer register.
        // Only follow the stable host pointer and WHD2 header's table pointers.
        // Field() separately bounds every index and checks arithmetic overflow.
        if(address == 0 || address == 0xfffffffc || (address & 3) != 0)
            throw new Exception("Unexpected DSP pointer " + address.ToString("X8") + "; stopping, not probing.");
    }
    static uint Field(uint address, uint index, uint words = 11)
    {
        CheckPointer(address);
        if(words == 0 || words > 256 || index >= words)
            throw new Exception("Read outside bounded table; stopping.");
        checked { uint last = address + (words - 1) * 4; CheckPointer(last); }
        uint target = checked(address + checked(index * 4));
        CheckPointer(target);
        return Read(target);
    }
    static string HeaderMismatch(uint host, uint ids, uint values, uint count)
    {
        // Never follow a newly observed pointer; stop reading on a mismatch.
        uint actual = Read(0x18009070);
        if(actual != host) return Difference("host pointer", host, actual);
        actual = Field(host, 0);
        if(actual != 0x32444857) return Difference("WHD2 signature", 0x32444857, actual);
        actual = Field(host, 8);
        if(actual != count) return Difference("meter count", count, actual);
        actual = Field(host, 9);
        if(actual != ids) return Difference("meter ID table", ids, actual);
        actual = Field(host, 10);
        if(actual != values) return Difference("meter values table", values, actual);
        return null;
    }
    static string Difference(string field, uint expected, uint actual)
    {
        return String.Format("{0}: expected 0x{1:X8}, observed 0x{2:X8}", field, expected, actual);
    }
    static double RefreshMeters(IntPtr module, uint host, uint ids, uint values, uint count)
    {
        // Verify the same host/table metadata immediately before the single
        // permitted write. No caller-controlled write address or value.
        if(cancel) throw new OperationCanceledException("Cancelled before refresh.");
        HeaderRecovery.Verify(
            delegate { return HeaderMismatch(host, ids, values, count); },
            Say, delegate { Thread.Sleep(50); }, delegate { return cancel; });
        if(cancel) throw new OperationCanceledException("Cancelled after header verification.");
        uint flagAddress = checked(host + 11u * 4u);
        CheckPointer(flagAddress);
        if(Read(flagAddress) != 0)
            throw new Exception("Refresh flag is not idle; stopping without writing.");
        WriteDsp request = Function<WriteDsp>(module, "WriteI2CRegister_DSP");
        Stopwatch ack = Stopwatch.StartNew();
        if(request(0x5a, flagAddress, 1, 4) == 0)
            throw new Exception("Refresh request failed; stopping without retry.");
        // Matches readHeadPosition -> waitForUpdate(reason=0, timeout=1000):
        // write word 11=1, sleep 5ms, poll until the device clears it to zero.
        // Never clear the flag ourselves, even on error or timeout.
        while(ack.ElapsedMilliseconds < 1000)
        {
            if(cancel) throw new OperationCanceledException("Cancelled while waiting for refresh.");
            Thread.Sleep(5);
            uint flag = Read(flagAddress);
            if(ack.ElapsedMilliseconds >= 1000) break;
            if(flag == 0) return ack.Elapsed.TotalMilliseconds;
            if(flag != 1) throw new Exception("Unexpected refresh flag value; stopping.");
        }
        throw new Exception("Refresh acknowledgement timed out after 1 second; no further refresh writes.");
    }
    static int Main(string[] args)
    {
        // Test the actual recovery policy without opening a DLL or device.
        if(args.Length == 1 && args[0] == "--self-test") return HeaderRecovery.SelfTest();
        string report = Path.Combine(AppDomain.CurrentDomain.BaseDirectory,
            "Orbit_Bridge_Report_" + DateTime.Now.ToString("yyyyMMdd_HHmmss_fff") + ".txt");
        try { log = new StreamWriter(new FileStream(report, FileMode.CreateNew, FileAccess.Write)); log.AutoFlush = true; }
        catch(Exception e) { Console.WriteLine("Cannot create report: " + e.Message); return 1; }
        Console.CancelKeyPress += delegate(object sender, ConsoleCancelEventArgs e) { cancel = true; e.Cancel = true; };
        // Watch for lack of progress, not total session duration.
        Timer watchdog = new Timer(delegate(object state) {
            double stalled = (Stopwatch.GetTimestamp() - Interlocked.Read(ref progressTicks)) / (double)Stopwatch.Frequency;
            if(stalled > 30) Environment.Exit(2);
        }, null, 1000, 1000);
        UdpClient udp = null;
        uint handle = 0;
        bool initialized = false;
        Close close = null;
        Uninit uninit = null;
        int result = 1;
        try
        {
            Say("Orbit to OpenTrack bridge v0.8 - continuous session, bounded header recheck");
            Say("UDP destination: 127.0.0.1:5252. Meter refresh only; no firmware/settings changes.");
            if(IntPtr.Size != 4) throw new Exception("Test must be compiled as x86.");
            if(Process.GetProcessesByName("OrbitBridge").Length > 1)
                throw new Exception("Another OrbitBridge is running. Close it before starting a new session.");
            if(Process.GetProcessesByName("Orbit").Length != 0)
                throw new Exception("Close the HyperX Orbit app completely, then run the test again.");
            string root = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86);
            if(String.IsNullOrEmpty(root)) root = Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles);
            string dll = Path.Combine(root, @"HyperX\Orbit\R2Clib.dll");
            if(!File.Exists(dll)) throw new Exception("Installed R2Clib.dll not found in the expected HyperX folder.");
            string hash;
            using(SHA256 sha = SHA256.Create())
            using(FileStream f = File.OpenRead(dll))
                hash = BitConverter.ToString(sha.ComputeHash(f)).Replace("-", "").ToLowerInvariant();
            Say("DLL SHA256: " + hash);
            if(hash != "70503bf228905ab6f2df3f8af2e9cfb0aa31e8aed594bb2d4e34147fa86abe8d")
                throw new Exception("DLL differs from the inspected version. Stopping without loading it.");
            // Search dependencies only in DLL directory and System32.
            IntPtr module = LoadLibraryEx(dll, IntPtr.Zero, 0x100 | 0x800);
            if(module == IntPtr.Zero) throw new Exception("DLL load failed, Windows error " + Marshal.GetLastWin32Error());
            Init init = Function<Init>(module, "RvcLib_Initialize");
            Open open = Function<Open>(module, "UAC_Open");
            close = Function<Close>(module, "UAC_Close");
            uninit = Function<Uninit>(module, "RvcLib_UnInitialize");
            read = Function<ReadDsp>(module, "ReadI2CRegister_DSP");
            Say("Initializing vendor interface...");
            if(init(0, 0) == 0) throw new Exception("Vendor initialization returned failure.");
            initialized = true;
            Say("Opening VID 0951 / PID 1703...");
            handle = open(0x0951, 0x1703);
            if(handle == 0) throw new Exception("Could not open headset. Check USB connection and close Orbit.");
            uint host = Read(0x18009070);
            Say("Host data pointer: " + host.ToString("X8"));
            if(Read(0x18009070) != host) throw new Exception("Host pointer changed between reads; stopping.");
            CheckPointer(host);
            uint magic = Field(host, 0);
            Say("Host signature: " + magic.ToString("X8"));
            if(magic != 0x32444857) throw new Exception("Expected WHD2 signature not found. Stopping.");
            uint count = Field(host, 8), ids = Field(host, 9), values = Field(host, 10);
            Say(String.Format("Meter count={0}; IDs={1:X8}; values={2:X8}", count, ids, values));
            CheckPointer(ids); CheckPointer(values);
            if(count < 4 || count > 256) throw new Exception("Unexpected meter count; stopping.");
            if(Field(host, 0) != 0x32444857 || Field(host, 8) != count ||
               Field(host, 9) != ids || Field(host, 10) != values)
                throw new Exception("Header changed between reads; stopping.");
            bool[] found = new bool[4];
            for(uint i = 0; i < count; i++)
            {
                uint id = Field(ids, i, count);
                if(id >= 13 && id <= 16) found[(int)(id - 13)] = true;
            }
            foreach(bool f in found) if(!f) throw new Exception("Orientation meter IDs 13-16 not all advertised.");
            udp = new UdpClient(AddressFamily.InterNetwork);
            IPEndPoint destination = new IPEndPoint(IPAddress.Loopback,5252);
            double[] center = null;
            Say("Continuous session. First valid pose becomes center.");
            Say("Use F9 in the game to center; Ctrl+C in the launcher stops the session.");
            Say("seconds,yaw_deg,pitch_deg,roll_deg,average_hz,refresh_ms");
            Stopwatch sw = Stopwatch.StartNew();
            int samples = 0;
            double largestChange = 0;
            double[] first = null;
            Interlocked.Exchange(ref progressTicks, Stopwatch.GetTimestamp());
            while(!cancel)
            {
                double refreshMs = RefreshMeters(module, host, ids, values, count);
                // Application reads signed Q31 records 13,14,15,16 and stores
                // QQuaternion in scalar,x,y,z order using 13,14,16,15.
                double[] q = new double[4];
                uint[] order = {13,14,16,15};
                for(int i=0; i<4; i++) q[i] = unchecked((int)Field(values, order[i], 17)) / 2147483648.0;
                double norm = Math.Sqrt(q[0]*q[0]+q[1]*q[1]+q[2]*q[2]+q[3]*q[3]);
                if(norm < 0.8 || norm > 1.2) throw new Exception("Unexpected orientation norm. Stopping rather than interpreting invalid data.");
                for(int i=0;i<4;i++) q[i] /= norm;
                if(center == null) center = (double[])q.Clone();
                while(!Console.IsInputRedirected && Console.KeyAvailable) {
                    ConsoleKey key = Console.ReadKey(true).Key;
                    if(key == ConsoleKey.C) { center=(double[])q.Clone(); Say("Recentered."); }
                    if(key == ConsoleKey.Q) cancel=true;
                }
                if(cancel) break;
                double[] angles=Angles(q,center);
                byte[] packet=Packet(angles);
                udp.Send(packet,packet.Length,destination);
                Interlocked.Exchange(ref progressTicks, Stopwatch.GetTimestamp());
                if(first == null) first = (double[])q.Clone();
                for(int i=0; i<4; i++) largestChange = Math.Max(largestChange, Math.Abs(q[i]-first[i]));
                samples++;
                Say(String.Format(CultureInfo.InvariantCulture,"{0:F3},{1:F2},{2:F2},{3:F2},{4:F2},{5:F1}",
                    sw.Elapsed.TotalSeconds,angles[0],angles[1],angles[2],samples/sw.Elapsed.TotalSeconds,refreshMs));
            }
            Say(String.Format(CultureInfo.InvariantCulture,"Samples={0}; largest component change={1:F6}",samples,largestChange));
            if(largestChange < 0.000001) Say("WARNING: No meaningful component change detected. Live tracking is NOT confirmed.");
            Say("Session ended. Stop tracking in OpenTrack.");
            result = 0;
        }
        catch(Exception e) { Say("STOPPED: " + e.Message); }
        finally
        {
            if(udp != null) udp.Close();
            try { if(handle != 0 && close != null) { Say("Closing device..."); close(handle); } }
            catch(Exception e) { Say("Close error: " + e.Message); }
            try { if(initialized && uninit != null) { Say("Releasing vendor interface..."); uninit(0); } }
            catch(Exception e) { Say("Cleanup error: " + e.Message); }
            Say("Report: " + report);
            watchdog.Dispose();
            lock(logLock) { log.Dispose(); log = null; }
        }
        return result;
    }
}

// No hardware writes here. Only the original metadata can be accepted.
static class HeaderRecovery
{
    public static void Verify(Func<string> mismatch, Action<string> log,
                              Action wait, Func<bool> cancelled)
    {
        if(cancelled()) throw new OperationCanceledException();
        string problem = mismatch();
        if(problem == null) return;
        log("RECOVERY: " + problem + "; suspending refresh writes for read-only rechecks.");
        int consecutive = 0;
        for(int attempt = 1; attempt <= 4; attempt++)
        {
            if(cancelled()) throw new OperationCanceledException();
            wait();
            if(cancelled()) throw new OperationCanceledException();
            problem = mismatch();
            consecutive = problem == null ? consecutive + 1 : 0;
            log("RECOVERY: recheck " + attempt + ": " + (problem ?? "original header matched"));
            if(consecutive == 2)
            {
                log("RECOVERY: original header matched twice consecutively; normal validation resumes.");
                return;
            }
        }
        throw new InvalidOperationException("Header did not stabilize to its original values after four read-only rechecks; no refresh write issued.");
    }
    public static int SelfTest()
    {
        try
        {
            Check(new string[]{null}, false, 1);
            Check(new string[]{"bad",null,null}, false, 3);
            Check(new string[]{"bad",null,"bad",null,null}, false, 5);
            Check(new string[]{"bad","bad","bad","bad","bad"}, true, 5);
            Check(new string[]{"bad",null,"bad",null,"bad"}, true, 5);
            int reads = 0;
            bool stopped = false;
            try { Verify(delegate { reads++; return null; }, delegate(string s){},
                         delegate {}, delegate { return true; }); }
            catch(OperationCanceledException) { stopped = true; }
            if(!stopped || reads != 0) throw new Exception("Cancellation test failed.");
            bool cancel = false;
            reads = 0; stopped = false;
            try { Verify(delegate { reads++; return "bad"; }, delegate(string s){},
                         delegate { cancel = true; }, delegate { return cancel; }); }
            catch(OperationCanceledException) { stopped = true; }
            if(!stopped || reads != 1) throw new Exception("Recovery cancellation failed.");
            stopped = false;
            try { Verify(delegate { throw new System.IO.IOException("read failure"); },
                         delegate(string s){}, delegate {}, delegate { return false; }); }
            catch(System.IO.IOException) { stopped = true; }
            if(!stopped) throw new Exception("Read failure was swallowed.");
            Console.WriteLine("Header recovery self-tests passed; no hardware accessed.");
            return 0;
        }
        catch(Exception e) { Console.WriteLine("SELF-TEST FAILED: " + e.Message); return 1; }
    }
    static void Check(string[] sequence, bool expectStop, int expectedReads)
    {
        int reads = 0;
        bool stopped = false;
        try
        {
            Verify(delegate {
                if(reads >= sequence.Length) throw new Exception("Unexpected extra header read.");
                return sequence[reads++];
            }, delegate(string s){}, delegate {}, delegate { return false; });
        }
        catch(InvalidOperationException) { stopped = true; }
        if(stopped != expectStop || reads != expectedReads)
            throw new Exception("Header confirmation sequence failed.");
    }
}
