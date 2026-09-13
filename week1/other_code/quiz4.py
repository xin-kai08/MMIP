import cv2
import numpy as np

def preprocess_image(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    
    return gray

def find_alignment(gray1, gray2):
    sift = cv2.SIFT_create()
    key_point1, descriptor1 = sift.detectAndCompute(gray1,  None)
    key_point2, descriptor2 = sift.detectAndCompute(gray2,  None)

    good_matches = []
    inlier_matches = []
    matrix = None
    
    if descriptor1 is None or descriptor2 is None:
        print("特徵不足無法配對")
        
        return matrix, key_point1, key_point2, good_matches, inlier_matches

    matcher = cv2.BFMatcher(cv2.NORM_L2)
    matches = matcher.knnMatch(descriptor1, descriptor2, k=2)
    
    for pair in matches:
        if len(pair) < 2:
            continue
        
        best, second = pair
        
        if best.distance < 0.75 * second.distance:
            good_matches.append(best)
    
    
    if len(good_matches) < 4:
        print("配對不足四組，無法估計透視轉換")
        
        return matrix, key_point1, key_point2, good_matches, inlier_matches
    
    points1 = []
    points2 = []
    
    for match in good_matches:
        points1.append(key_point1[match.queryIdx].pt)
        points2.append(key_point2[match.trainIdx].pt)
    
    points1 = np.array(points1, dtype=np.float32)
    points2 = np.array(points2, dtype=np.float32)
    
    matrix, mask = cv2.findHomography(points1, points2, cv2.RANSAC, 5.0)
    
    if matrix is None or mask is None:
        print("無法估計有效的透視矩陣")
        
        return matrix, key_point1, key_point2, good_matches, inlier_matches
    
    for index, is_inlier in enumerate(mask.ravel()):
        if is_inlier == 1:
            inlier_matches.append(good_matches[index])
            
    return matrix, key_point1, key_point2, good_matches, inlier_matches

def stitch_image(image1, image2, matrix):
    if matrix is None:
        print("沒有有效的轉換矩陣，無法拼接")
        
        return None
    
    height1, width1 = image1.shape[:2]
    height2, width2 = image2.shape[:2]
    corner1 = np.array([[0, 0], [width1, 0], [width1, height1], [0, height1]], dtype=np.float32).reshape(-1, 1, 2)
    corner2 = np.array([[0, 0], [width2, 0], [width2, height2], [0, height2]], dtype=np.float32).reshape(-1, 1, 2)
    
    transformed_corner1 = cv2.perspectiveTransform(corner1, matrix)
    all_corner = np.concatenate((transformed_corner1, corner2), axis=0).reshape(-1, 2)
    
    x_min, y_min = np.floor(all_corner.min(axis=0)).astype(int)
    x_max, y_max = np.ceil(all_corner.max(axis=0)).astype(int)
    canvas_width = int(x_max - x_min)
    canvas_height = int(y_max - y_min)
    
    shift_x = int(-x_min)
    shift_y = int(-y_min)
    translation = np.array([
        [1, 0, shift_x],
        [0, 1, shift_y],
        [0, 0, 1]
    ], dtype=np.float64)
    
    stitched = cv2.warpPerspective(image1, translation @ matrix, (canvas_width, canvas_height))
    
    stitched[shift_y:shift_y + height2, shift_x:shift_x + width2] = image2
    
    return stitched