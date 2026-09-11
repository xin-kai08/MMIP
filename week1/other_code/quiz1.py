import numpy as np

def grayscale_mean(image):
    height, width = image.shape[:2]
    gray_image = np.zeros((height, width), dtype=np.uint8)
    
    for row in range(height):
        for col in range(width):
            b, g, r = map(int, image[row, col])
            gray_image[row, col] = (r + g + b) // 3
    
    return gray_image