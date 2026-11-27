from PIL import Image, ImageDraw, ImageFont

# Open images
left_img = Image.open("data/quiz2/set1/left.jpg")
right_img = Image.open("data/quiz2/set1/right.jpg")
panorama_img = Image.open("result/quiz3/agent/run_60a13a7698/panorama_9f556e06.png")

# Define scales
scale = 0.5

# Resize images
left_resized = left_img.resize((int(left_img.width * scale), int(left_img.height * scale)))
right_resized = right_img.resize((int(right_img.width * scale), int(right_img.height * scale)))
panorama_resized = panorama_img.resize((int(panorama_img.width * scale), int(panorama_img.height * scale)))

# Calculate canvas dimensions
canvas_width = max(left_resized.width, right_resized.width, panorama_resized.width) + 100
canvas_height = max(left_resized.height, right_resized.height, panorama_resized.height) + 100

# Create canvas
canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')

# Paste images
canvas.paste(left_resized, (0, 0))
canvas.paste(right_resized, (canvas_width - right_resized.width, 0))
canvas.paste(panorama_resized, (0, canvas_height - panorama_resized.height))

# Draw captions
draw = ImageDraw.Draw(canvas)
font = ImageFont.load_default(size=22)

draw.text((10, 10), "Left: 1108 x 1477", fill="black", font=font)
draw.text((canvas_width - 10, 10), "Right: 1108 x 1477", fill="black", font=font)
draw.text((10, canvas_height - 10), "Panorama: 1776 x 1368", fill="black", font=font)

# Save canvas
canvas.save("result/quiz3/agent/run_60a13a7698/comparison.png")
