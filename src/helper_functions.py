import os
import re
import sys
import psutil
import shutil
import subprocess
import json
from pathlib import Path

# TODO: Switch to logging instead of printing errors

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
            "used": used_gib,
            "total": total_gib,
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
    swap_list = {
        "zram": {
            "enabled": False,
            "path": None,
            "size": None,
            "priority": None,
            "algorithm": None
        },
        "swap": {
            "enabled": False,
            "type": None,
            "path": None,
            "size": None,
            "priority": None,
            "zswap_enabled": None,
            "zswap_algorithm": None
        }
    }

    try:
        with open("/proc/swaps", "r") as f: # An example swaps file layout: Filename                                Type            Size            Used            Priority
                                            #                               /dev/zram0                              partition       12017660        1750244         100
                                            #                               /dev/sda3                               partition       12093436        0               -1
            swaps = f.readlines()
        
            slz = swap_list["zram"]
            sls = swap_list["swap"]

            for swap in swaps[1:]: # Skip the header line
                data = swap.split()

                swap_path = data[0]

                if "zram" in data[0]:
                    swap_type = "zram"
                else:
                    swap_type = data[1]
                
                swap_size = round(int(data[2]) / (1024 ** 2), 1) # Convert to GiB and round to 1 decimal place to make it easy to read
                swap_priority = int(data[4]) # Convert priority data to integer

                if swap_type == "zram":
                    zram = get_zram_information()
                    slz["enabled"] = True
                    slz["path"] = swap_path
                    slz["size"] = swap_size
                    slz["priority"] = swap_priority
                    slz["algorithm"] = zram["algorithm"]
                
                else:
                    sls["enabled"] = True
                    sls["type"] = swap_type
                    sls["path"] = swap_path[5:] # Clean '/dev/' prefix
                    sls["size"] = swap_size
                    sls["priority"] = swap_priority

            zswap = get_zswap_information()
            sls["zswap_enabled"] = zswap["enabled"]
            sls["zswap_algorithm"] = zswap["algorithm"]

    except Exception as e:
        print(f"Error while reading swap information: {e}")
    
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

def get_zswap_information():
    zswap_info_dir = Path("/sys/module/zswap")

    try:
        if not zswap_info_dir.exists():
            return {
                "status": True,
                "enabled": False,
                "algorithm": None,
                "message": "Zswap module not loaded"
            }
        
        with open(zswap_info_dir / "parameters/enabled", "r") as f:
            parameters_enabled = f.read().strip()
            enabled = parameters_enabled in ("Y", "1")

        with open(zswap_info_dir / "parameters/compressor", "r") as f:
            algorithm = f.read().strip()

        return {
            "status": True,
            "enabled": enabled,
            "algorithm": algorithm,
            "message": "Success"
        }
    except Exception as e:
        return {
            "status": False,
            "enabled": None,
            "algorithm": None,
            "message": e
        }

def get_zram_information():
    try:     
        with open("/sys/block/zram0/comp_algorithm", "r") as f:
            current_algorithm = re.search(r'\[(.*?)\]', f.read()).group(1)
            return {
                "status": True,
                "enabled": True,
                "algorithm": current_algorithm,
                "message": "Success"
            }
    except Exception as e:
        return {
            "status": False,
            "enabled": None,
            "algorithm": None,
            "message": e
        }
    
def get_swappiness():
    try:
        with open("/proc/sys/vm/swappiness", "r") as f:
            swappiness = int(f.read().strip())
        return swappiness
    except:
        return 0

def get_usable_compression_algorithms():
    suggested_algorithms = ["lz4", "zstd", "lzo", "lzo-rle"]
    usable_algorithms = []

    for algorithm in suggested_algorithms:
        try:
            command = subprocess.run(
                ["modprobe", algorithm],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            print(f"Module {algorithm} is enabled")
        
        except subprocess.CalledProcessError as e:
            print(f"Module {algorithm} failed: {e}")

    try:
        with open("/proc/crypto", "r") as f:
            crypto_support = f.read()

            for algorithm in suggested_algorithms:
                if algorithm in crypto_support:
                    usable_algorithms.append(algorithm)
    
    except Exception as e:
        print(f"Error while reading /proc/crypto: {e}")

    return usable_algorithms

def get_partitions():
    partitions = []

    try:
        list_blocks = subprocess.run(
            ["lsblk", "-J", "-o", "NAME" ],
            capture_output=True,
            text=True,
            check=True,
        )

        data = json.loads(list_blocks.stdout)
        for disk in data["blockdevices"]:
            for param in disk:
                if "children" in param:
                    for partition in disk["children"]:
                        partitions.append(partition["name"])

    except Exception as e:
        print(f"Error while getting partitions: {e}")
    
    return partitions

def set_swappiness(value):
    try:
        with open("/etc/sysctl.d/99-swappiness.conf", "w", encoding="UTF-8") as f:
            f.write(f"vm.swappiness = {value}\n")
    except PermissionError:
        print("Error while setting swappiness value: Permission error")
    except Exception as e:
        print(f"Error while setting swappiness: {e}")
    
    try:
        command = subprocess.run(
            ["sysctl", "--system"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print("Sysctl configuration reloaded")
    except subprocess.CalledProcessError as e:
        print(f"Error while reloading sysctl configuration: {e}")

def set_zram_configuration(zram_data):

    if zram_data["enabled"]:
        configuration = f"""[zram0]
zram-size = {int(zram_data["size"] * 1024)}
swap-priority = {zram_data["priority"]}
compression-algorithm = {zram_data["algorithm"]}
"""
        try:
            with open("/etc/systemd/zram-generator.conf", "w", encoding="UTF-8") as f:
                f.write(configuration)
        
        except PermissionError:
            print("Error while writing zram-generator.conf: PermissionError")
        
        except Exception as e:
            print(f"Error while writing zram-generator.conf: {e}")
        
        disable_and_mask_zram()
        enable_zram()

    else:
        disable_and_mask_zram()

def disable_and_mask_zram():
    try: # Stop the zram service
        command_zram_generator_stop = subprocess.run(
            ["systemctl", "stop", "systemd-zram-setup@zram0.service"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print("Zram service stopped")
    except subprocess.CalledProcessError as e:
        print(f"Error while stopping zram service: {e}")

    try: # Disable zram kernel module
        command_zram_generator_stop = subprocess.run(
            ["modprobe", "-r", "zram"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print("Zram kernel module removed")
    except subprocess.CalledProcessError as e:
        print(f"Error while removing zram kernel module: {e}")

    try:
        command_mask_zram_service = subprocess.run(
            ["systemctl", "mask", "systemd-zram-setup@zram0.service"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print("Zram service masked")
    except subprocess.CalledProcessError as e:
        print(f"Error while masking zram service: {e}")

def enable_zram():
    try: # unmask the zram service
        command_unmask_zram_service = subprocess.run(
            ["systemctl", "unmask", "systemd-zram-setup@zram0.service"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print("Unmasked zram service")
    except subprocess.CalledProcessError as e:
        print(f"Error while unmasking zram service")

    try: # Reload the daemon
        command_daemon_reload = subprocess.run(
            ["systemctl", "daemon-reload"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print("Systemctl daemon reloaded")
    except subprocess.CalledProcessError as e:
        print(f"Error while reloading systemd daemon: {e}")
    
    try: # start the zram service
        command_zram_generator_restart = subprocess.run(
            ["systemctl", "start", "systemd-zram-setup@zram0.service"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        print("Zram service reloaded")
    except subprocess.CalledProcessError as e:
        print(f"Error while reloading zram service: {e}")
