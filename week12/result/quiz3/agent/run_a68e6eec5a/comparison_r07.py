from PIL import Image, ImageDraw, ImageFont

# Open the images
left_image = Image.open("data/quiz2/set1/left.jpg")
right_image = Image.open("data/quiz2/set1/right.jpg")
panorama_image = Image.open("result/quiz3/agent/run_a68e6eec5a/panorama_1579a13f.png")

# Define the scale factor
scale_factor = 0.5

# Resize the images
left_resized = left_image.resize((int(left_image.width * scale_factor), int(left_image.height * scale_factor)))
right_resized = right_image.resize((int(right_image.width * scale_factor), int(right_image.height * scale_factor)))
panorama_resized = panorama_image.resize((int(panorama_image.width * scale_factor), int(panorama_image.height * scale_factor)))

# Calculate the canvas dimensions
canvas_width = left_resized.width + right_resized.width + panorama_resized.width
canvas_height = max(left_resized.height, right_resized.height, panorama_resized.height) + 40

# Create the canvas
canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')

# Paste the images onto the canvas
canvas.paste(left_resized, (0, 40))
canvas.paste(right_resized, (left_resized.width, 40))
canvas.paste(panorama_resized, (left_resized.width + right_resized.width, 40))

# Draw the captions
draw = ImageDraw.Draw(canvas)
draw.text((10, 10), "Left: 1108 x 1477", fill="black", font=ImageFont.load_default(size=22))
draw.text((left_resized.width + 10, 10), "Right: 1108 x 1477", fill="black", font=ImageFont.load_default(size=22))
draw.text((left_resized.width + right_resized.width + 10, 10), "Panorama: 1774 x 1368", fill="black", font=ImageFont.load_default(size=22))

# Save the canvas
canvas.save("result/quiz3/agent/run_a68e6eec5a/comparison.png")
