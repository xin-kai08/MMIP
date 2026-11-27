from PIL import Image, ImageDraw, ImageFont

# Load images
left = Image.open("data/quiz2/set1/left.jpg")
right = Image.open("data/quiz2/set1/right.jpg")
panorama = Image.open("result/quiz3/agent/run_85d5fd120a/panorama_9c98d1c9.png")

# Resize and save as thumbnails
left.thumbnail((100, 100), Image.ANTIALIAS)
right.thumbnail((100, 100), Image.ANTIALIAS)
panorama.thumbnail((100, 100), Image.ANTIALIAS)

# Calculate canvas size
canvas_width = max(left.width + right.width + panorama.width, 1000)
canvas_height = max(left.height + right.height + panorama.height, 1000)

# Create canvas
canvas = Image.new("RGB", (canvas_width, canvas_height), (255, 255, 255))
draw = ImageDraw.Draw(canvas)

# Draw titles and sizes
title_font = ImageFont.load_default(size=22)
draw.text((10, 10), f"Left {left.size[0]} x {left.size[1]}", font=title_font)
draw.text((10, 50), f"Right {right.size[0]} x {right.size[1]}", font=title_font)
draw.text((10, 90), f"Panorama {panorama.size[0]} x {panorama.size[1]}", font=title_font)

# Paste images onto canvas
canvas.paste(left, (0, 0))
canvas.paste(right, (left.width, 0))
canvas.paste(panorama, (left.width + right.width, 0))

# Save canvas
canvas.save("result/quiz3/agent/run_85d5fd120a/comparison.png")
