import subprocess
import os
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

def start_backend():
    backend_port = 8001
    print(f"Starting backend on port {backend_port}...")
    backend_dir = os.path.join(os.getcwd(), "backend")
    log_file = open(os.path.join(os.getcwd(), "backend.log"), "w")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008 if sys.platform == 'win32' else 0
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", str(backend_port), "--reload"],
        cwd=backend_dir,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags
    )

def start_frontend():
    frontend_port = 8081
    print(f"Starting frontend on port {frontend_port}...")
    frontend_dir = os.path.join(os.getcwd(), "frontend")
    log_file = open(os.path.join(os.getcwd(), "frontend.log"), "w")
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x00000008 if sys.platform == 'win32' else 0
    return subprocess.Popen(
        [sys.executable, "-m", "http.server", str(frontend_port)],
        cwd=frontend_dir,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags
    )

if __name__ == "__main__":
    kill_process_on_port(8000)
    kill_process_on_port(8001)
    kill_process_on_port(8081)
    
    be_proc = start_backend()
    fe_proc = start_frontend()
    
    print("\n--- Servers started ---")
    print("Frontend: http://localhost:8081")
    print("Backend:  http://localhost:8001")
    print("Logs written to backend.log and frontend.log")
    print("Press Ctrl+C to stop.\n")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping servers...")
        be_proc.terminate()
        fe_proc.terminate()
