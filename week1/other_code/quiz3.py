import cv2
import numpy as np

def select_corners(image):
    height, width = image.shape[:2]
    
    scale = min(650 / height, 1000 / width, 1)
    display_height = max(1, round(height * scale))
    display_width = max(1, round(width * scale))
    preview = cv2.resize(image, (display_width, display_height))
    
    points = []
    window_name = "click corners: TL, TR, BR, BL | enter: confirm | R: reselect | ESC: exit"
    
    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 4:
            points.append((x, y))
            
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)
    cv2.imshow(window_name, preview)
    cv2.setMouseCallback(window_name, on_mouse)
    
    try:
        while True:
            canvas = preview.copy()
            for index, point in enumerate(points):
                cv2.circle(canvas, point, 5, (0, 0, 255), -1)
                cv2.putText(canvas, str(index + 1), (point[0] + 8, point[1] + 8), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            
            if len(points) >= 2:
                contour = np.array(points, dtype=np.int64)
                cv2.polylines(canvas, [contour], len(points) == 4, (0, 255, 0), 2)
                
            cv2.imshow(window_name, canvas)
            key = cv2.waitKey(20) & 0xFF
            
            if cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1:
                return None

            if key == 27:
                return None
            
            if key in (ord("r"), ord("R")):
                points.clear()
                
            if key in (10, 13) and len(points) == 4:
                contour = np.array(points, dtype=np.float32)
                
                if (not cv2.isContourConvex(contour) or cv2.contourArea(contour) < 1):
                    print("四點順序或位置不正確，請按R重選")
                    continue
                
                source_points = np.array(points, dtype=np.float32)
                source_points[:, 0] *= width / display_width
                source_points[:, 1] *= height / display_height
                
                return source_points
    finally:
        try:
            cv2.destroyWindow(window_name)
            cv2.waitKey(1)
        except cv2.error:
            pass

def correct_perspective(image, source_points):
    output_width = 700
    output_height = 900
    destination_points = np.float32([[0, 0], [output_width - 1, 0], [output_width - 1, output_height - 1], [0, output_height - 1]])
    
    matrix = cv2.getPerspectiveTransform(source_points, destination_points)
    corrected = cv2.warpPerspective(image, matrix, (output_width, output_height))
    
    return corrected