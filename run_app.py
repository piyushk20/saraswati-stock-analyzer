import subprocess
import os
import signal
import sys
import time
import socket

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def kill_process_on_port(port):
    if not is_port_in_use(port):
        return
    print(f"Killing process on port {port}...")
    if sys.platform == 'win32':
        try:
            output = subprocess.check_output(f"netstat -ano | findstr :{port}", shell=True).decode()
            for line in output.splitlines():
                if "LISTENING" in line:
                    pid = line.strip().split()[-1]
                    subprocess.run(f"taskkill /F /PID {pid}", shell=True)
        except:
            pass
    else:
        subprocess.run(f"fuser -k {port}/tcp", shell=True)

def start_backend():
    backend_port = 8000
    print(f"Starting backend on port {backend_port}...")
    backend_dir = os.path.join(os.getcwd(), "backend")
    # Using python -m uvicorn ensure we use the right environment
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(backend_port), "--reload"],
        cwd=backend_dir
    )

def start_frontend():
    print("Starting frontend on port 8080...")
    frontend_dir = os.path.join(os.getcwd(), "frontend")
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", "8080"],
        cwd=frontend_dir
    )

if __name__ == "__main__":
    kill_process_on_port(8000)
    kill_process_on_port(8080)
    
    be_proc = start_backend()
    fe_proc = start_frontend()
    
    print("\n--- Servers started ---")
    print("Frontend: http://localhost:8080")
    print("Backend:  http://localhost:8000")
    print("Press Ctrl+C to stop.\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping servers...")
        be_proc.terminate()
        fe_proc.terminate()
