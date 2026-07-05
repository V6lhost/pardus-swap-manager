import os
import sys
import psutil
from pathlib import Path


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