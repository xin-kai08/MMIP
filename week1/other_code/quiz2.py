import numpy as np

def equalized_numpy(image):
    height, width = image.shape
    total_pixel = height * width
    histogram = np.zeros(256, dtype=np.int64)
    
    for row in range(height):
        for col in range(width):
            value = int(image[row, col])
            histogram[value] += 1
    
    cumulative = np.zeros(256, dtype=np.int64)
    running_total = 0
    
    for idx in range(256):
        running_total += histogram[idx]
        cumulative[idx] = running_total
        
    first_idx = np.flatnonzero(histogram)[0]
    count_min = cumulative[first_idx]
    
    lookup_table = np.zeros(256, dtype=np.int64)
    for idx in range(first_idx, 256):
        new_idx = ((cumulative[idx] - count_min) / (total_pixel - count_min) * 255)
        lookup_table[idx] = int(round(new_idx))
        
    result = np.zeros((height, width), dtype=np.uint8)
    for row in range(height):
        for col in range(width):
            result[row, col] = lookup_table[image[row, col]]
            
    return result