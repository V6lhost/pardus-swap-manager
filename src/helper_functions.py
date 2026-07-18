import os
import re
import sys
import psutil
import shutil
import subprocess
import json
from pathlib import Path

# Create temp directory  and define last results directory
tmp_dir = Path('/tmp/pardus-swap-manager')
tmp_dir.mkdir(parents=True, exist_ok=True)
last_results_dir = tmp_dir / 'last_results'

def get_memory_status(mem_type="ram"):
    try:
        # Switch to swap if the given type is swap
        if mem_type == "swap":
            memory = psutil.swap_memory()
        else:
            memory = psutil.virtual_memory()

        # Convert to GiBs and round to 1 decimal place
        used_gib = round((memory.used / (1024 ** 3)), 1)
        total_gib = round((memory.total / (1024 ** 3)), 1)

        percentage = memory.percent

        return {
            "used": f"{used_gib} GiB",
            "total": f"{total_gib} GiB",
            "percentage": percentage
        }

    except Exception as e:
        print(f"Error while reading {mem_type} status: {e}. Returning zero fallback dictionary.")
        
        return {
            "used": 0,
            "total": 0,
            "percentage": 0
        }


def get_swap_information():
    swap_list = []

    try:
        with open("/proc/swaps", "r", encoding="utf-8") as f:
            swaps = f.readlines()

            for swap in swaps[1:]: # Skip the header line
                data = swap.split()
                if len(data) >= 5:

                    swap_list.append({
                        "path": data[0],
                        "swap_type": data[1],
                        "size": round(int(data[2]) / (1024 ** 2), 1), # Convert to GiB and round to 1 decimal place
                        "priority": data[4]
                    })
            
            return swap_list
    
    except Exception as e:
        print(f"Error while reading /proc/swaps file: {e}. Returning empty fallback list.")
        return swap_list


def check_cpu_avx_support(): # Its a simple way to check if the system has a modern CPU to handle ZSTD compression
    try:
        with open("/proc/cpuinfo", "r", encoding="utf-8") as f:
            data = f.read().lower()
            
            if "avx" in data:
                return True
            
            else:
                return False
    
    except Exception as e:
        print(f"Error while reading cpu instructions: {e}. Continuing with fallback LZ4")
        return False


def get_disk_type():
    try:
        disks = os.listdir("/sys/block")

        for disk in disks:
            full_path = os.path.realpath(f"/sys/block/{disk}") # Get the full path of disk

            if "usb" not in full_path and "zram" not in full_path and "loop" not in full_path: # Filter the usb, zram and loop devices

                # Check the disk type for better swap suggestion
                if "nvme" in disk:
                    return "NVMe"
                
                else:
                    with open(f"/sys/block/{disk}/queue/rotational", "r") as f: # Get the spin information for detecting HDDs
                        data = f.read()

                        if data.strip() == "0":
                            return "SSD"
                        else:
                            return "HDD"
                  
        return "Portable" # Fallback if the system has no drives. Possibly a portable USB installation.
    
    except Exception as e:
        print(f"Error while reading disk information: {e}. Continuing with fallback 'Undetected'.")
        return "Undetected"


def check_swap_requirement():
    # Collect information
    ram_size = round((psutil.virtual_memory().total) / (1024 ** 3))
    avx_support = check_cpu_avx_support()
    disk_type = get_disk_type()
    
    # Decide the ZRAM/SWAP combination
    if ram_size >= 15:
        return "Optional zRAM"
    elif ram_size >= 11:
        return "zRAM"
    elif ram_size >= 7:
        if disk_type == "HDD":
            return "zRAM"
        else:
            return "zRAM and SWAP"
    else:
        if avx_support:
            return "zRAM and SWAP"
        else:
            return "SWAP"


def prepare_silesia_benchmark_data(status_callback):
    try:
        # Define file paths and download url
        silesia_tar_path = Path(tmp_dir) / 'silesia.tar'
        silesia_zip_path = Path(tmp_dir) / 'silesia.zip'
        silesia_extract_path = Path(tmp_dir) / 'silesia_extracted/'
        silesia_zip_url = "https://sun.aei.polsl.pl/~sdeor/corpus/silesia.zip"

        # Download Silesia benchmark data. pass download if its already installed
        if not silesia_tar_path.exists():
            if silesia_zip_path.exists():
                silesia_zip_path.unlink()
            if silesia_extract_path.exists() and silesia_tar_path.exists(): # they both will be exists if a problem happens or thread is closed by user. detect it and clean
                silesia_tar_path.unlink()
            if silesia_extract_path.exists():
                shutil.rmtree(silesia_extract_path)

            silesia_download_command = ['curl', '-L', '-#', '-o', str(silesia_zip_path), str(silesia_zip_url)]

            with subprocess.Popen(
                silesia_download_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            ) as download_process:
                # Call a calback function to upgrade percentage
                last_percentage = None

                for line in download_process.stdout:
                    match = re.search(r"(\d+(?:\.\d+)?)%", line)
                    if match:
                        percentage = int(float(match.group(1)))
                        if percentage != last_percentage: # Run the callback function if only percentage is not same as the before. 
                            status_callback(percentage)
                            last_percentage = percentage
                
                return_code = download_process.wait()

                if return_code != 0:
                    raise RuntimeError("Download failed")
        
            # Unzip the archive
            unzip_command = ['unzip', '-d', str(silesia_extract_path), str(silesia_zip_path)]
            subprocess.run(unzip_command, check=True)
            
            # Cleanup unnecessary files
            silesia_zip_path.unlink()

            # Archive the extracted zip as tar without compression
            tar_command = ['tar', '-cf', str(silesia_tar_path), '-C', str(silesia_extract_path), '.']
            subprocess.run(tar_command, check=True)

            # Clean extracted file directory
            shutil.rmtree(silesia_extract_path)

    except Exception as e:
        raise RuntimeError(f"Process prepare Silesia failed: {e}")


def benchmark_disk(path):
    try:
        last_results_dir.mkdir(parents=True, exist_ok=True)
        disk_benchmark_result_file = last_results_dir / 'disk_benchmark_results.json'
        test_folder = Path(path) / ".tmp_fio"
        test_file = Path(test_folder) / 'test_fio.tmp'

        # Return latest benchmark results if available
        cached_result = load_result_from_cache(disk_benchmark_result_file)
        if cached_result != None:
            return cached_result

        if test_folder.exists():
            shutil.rmtree(test_folder)

        test_folder.mkdir()
        check_and_disable_cow(test_folder)

        # Test command for benchmarking random read-write/iops speed
        command = [
            "fio", "--name=swap_sim", f"--filename={test_file}",
            "--ioengine=libaio", "--direct=1", "--bs=4k", "--rw=randrw",
            "--rwmixread=70", "--size=64M", "--runtime=10", "--time_based",
            "--output-format=json"
        ]

        process = subprocess.run(command, capture_output=True, text=True, check=True)

        data = json.loads(process.stdout)
        
        # Gather the useful information
        useful_data = data['jobs'][0]
        
        dict_data = {
            "read_iops": round(useful_data['read']['iops']), # Round to an integer
            "read_speed": round((useful_data['read']['bw'] / 1024), 1), # Convert KB/s to MB/s and round to 1 decimal place
            "read_latency": round((useful_data['read']['clat_ns']['mean'] / 1000000), 3), # Convert nanoseconds to miliseconds and round to 3 decimal place
            "write_iops": round(useful_data['write']['iops']), # Round to an integer
            "write_speed": round((useful_data['write']['bw'] / 1024), 1), # Convert KB/s to MB/s and round to 1 decimal place
            "write_latency": round((useful_data['write']['clat_ns']['mean'] / 1000000), 3) # Convert nanoseconds to miliseconds and round to 3 decimal place 
        }

        with open(disk_benchmark_result_file, 'w', encoding='utf-8') as f:
            json.dump(dict_data, f)
        
        return dict_data

    
    except subprocess.CalledProcessError as e:
        error_code = e.returncode
        error_message = e.stdout

        print(f"Error while benchmarking disk. Maybe fio is not installed? Continuing with fallback. Error code: {error_code} Message: {error_message}")
        
        return {
            "read_iops": 0,
            "read_speed": 0,
            "read_latency": 0,
            "write_iops": 0,
            "write_speed": 0,
            "write_latency": 0
        }

    finally:
        if test_folder.exists():
            shutil.rmtree(test_folder)


def benchmark_algorithm(algorithm):
    try:
        last_results_dir.mkdir(parents=True, exist_ok=True)

        benchmark_algorithm_result_file = last_results_dir / f"{algorithm}_benchmark_results.json" 

        # Return latest benchmark results if available
        cached_result = load_result_from_cache(benchmark_algorithm_result_file)
        if cached_result != None:
            return cached_result

        silesia_tar_path = Path(tmp_dir) / 'silesia.tar'
        
        # Run the benchmark command for given algorithm
        benchmark_command = [algorithm, '-b1', '-e1', str(silesia_tar_path)]
        benchmark_process = subprocess.run(benchmark_command, capture_output=True, text=True, check=True)

        data = parse_compression_results(benchmark_process.stdout)
        
        with open(benchmark_algorithm_result_file, 'w', encoding='utf-8') as f:
            json.dump(data, f)

        return data
    
    except Exception as e:
        print(f"Error while benchmarking algorithm: {e}")

        return {
            "compress_speed": 0,
            "decompress_speed": 0,
        }


def clear_cache():
    try:
        if last_results_dir.exists():
            shutil.rmtree(last_results_dir)
        return True
    except Exception as e:
        return False


def check_and_disable_cow(path): # CoW and compression features in BTRFS filesystems causes low swap performance. We have to disable them for benchmark folder to succesfully benchmark
    if not path.exists():
        print(f"{path} does not exists")
        return False
    if not path.is_dir():
        print(f"{path} is not a folder")
        return False
    
    try:
        result = subprocess.run(
            ['lsattr', '-d', path],
            capture_output=True,
            text=True,
            check=True
        )

        attributes = result.stdout.split()[0]

        if 'C' not in attributes:
            subprocess.run(['chattr', '+C', path], check=True)
        
        return True
    
    except Exception:
        return False


def score_by_threshold(value, thresholds): # Dynamic score function
    for minimum, score in thresholds:
        if value >= minimum:
            return score
    return 0


def load_result_from_cache(path):
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except json.JSONDecodeError:
        path.unlink()
        return None


def parse_compression_results(data):
    lines = data.splitlines()

    # Catch clean data from stdout
    pattern = r"([\d.]+)\s*MB/s(?:,\s*([\d.]+)\s*MB/s)?"

    compress_speed = 0
    decompress_speed = 0

    for line in reversed(lines):
        match = re.search(pattern, line)
        if match:
            if match.group(1) and match.group(2):
                # Convert to integer
                compress_speed = int(float(match.group(1)))
                decompress_speed = int(float(match.group(2)))
                break
            elif match.group(1) and compress_speed == 0:
                compress_speed = int(float(match.group(1)))
    
    return {
        "compress_speed": compress_speed,
        "decompress_speed": decompress_speed
    }