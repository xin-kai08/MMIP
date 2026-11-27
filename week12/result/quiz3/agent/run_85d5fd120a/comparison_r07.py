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
title_font = ImageFont.truetype("arial.ttf", 22)
draw.text((10, 10), "Left", font=title_font, fill=(0, 0, 0))
draw.text((10, 30), f"{left.size[0]} x {left.size[1]}", font=title_font, fill=(0, 0, 0))
draw.text((10, 50), "Right", font=title_font, fill=(0, 0, 0))
draw.text((10, 70), f"{right.size[0]} x {right.size[1]}", font=title_font, fill=(0, 0, 0))
draw.text((10, 90), "Panorama", font=title_font, fill=(0, 0, 0))
draw.text((10, 110), f"{panorama.size[0]} x {panorama.size[1]}", font=title_font, fill=(0, 0, 0))

# Paste images onto canvas
canvas.paste(left, (0, 0))
canvas.paste(right, (left.width, 0))
canvas.paste(panorama, (left.width + right.width, 0))

# Save canvas
canvas.save("result/quiz3/agent/run_85d5fd120a/comparison.png")
