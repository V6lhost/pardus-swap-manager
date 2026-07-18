# Calibration data for scores. !! Current values are not realistic, just for testing purposes.

read_speed_score_table = [
    (80,100),
    (60,90),
    (40,80),
    (20,60),
    (10,30),
]

write_speed_score_table = [
    (40, 100),
    (30, 90),
    (20, 80),
    (10, 60),
    (5, 30),
]

read_latency_score_table = [
    (2, 0),
    (1, 20),
    (0.25, 50),
    (0.5, 70),
    (0.1, 90),
    (0.05, 100)
]

write_latency_score_table = [
    (2, 0),
    (1, 25),
    (0.15, 50),
    (0.3, 75),
    (0.5, 90),
    (0.8, 100)
]

read_iops_score_table = [
    (10000, 100),
    (8000, 90),
    (5000, 80),
    (3000, 60),
    (2000, 30)
]
    
write_iops_score_table = [
    (10000, 100),
    (7000, 90),
    (5000, 80),
    (2500, 60),
    (1000, 30)
]

zstd_compress_score_table = [
    (1000, 100),
    (700, 70),
    (500, 50),
    (300, 30)
]

zstd_decompress_score_table = [
    (1800, 100),
    (1500, 70),
    (1000, 50),
    (700, 30)
]

lz4_compress_score_table = [
    (1000, 100),
    (700, 70),
    (500, 50),
    (400, 30)
]

lz4_decompress_score_table = [
    (5000, 100),
    (3500, 70),
    (2000, 50),
    (1500, 30)
]

def calculate_disk_score(l, io):
    score = l * 0.6 + io * 0.4 # 60-40 ratio. 60 latency, 40 iops
    return(score)