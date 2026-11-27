from PIL import Image, ImageDraw, ImageFont

# Open the images
left_image = Image.open("data/quiz2/set1/left.jpg")
right_image = Image.open("data/quiz2/set1/right.jpg")
panorama_image = Image.open("result/quiz3/agent/run_c1e285578d/panorama_8f719181.png")

# Define the scale factor
scale_factor = 0.5

# Resize the images
left_resized = left_image.resize((int(left_image.width * scale_factor), int(left_image.height * scale_factor)))
right_resized = right_image.resize((int(right_image.width * scale_factor), int(right_image.height * scale_factor)))
panorama_resized = panorama_image.resize((int(panorama_image.width * scale_factor), int(panorama_image.height * scale_factor)))

# Create a canvas to fit all three images
canvas_width = max(left_resized.width, right_resized.width, panorama_resized.width)
canvas_height = max(left_resized.height, right_resized.height, panorama_resized.height) + 30  # Add some padding for text
canvas = Image.new('RGB', (canvas_width, canvas_height))

# Paste the images onto the canvas
canvas.paste(left_resized, (0, 0))
canvas.paste(right_resized, (0, left_resized.height))
canvas.paste(panorama_resized, (0, left_resized.height + right_resized.height))

# Load the default font
font = ImageFont.load_default(size=22)

# Draw the captions
draw = ImageDraw.Draw(canvas)
draw.text((10, 10), "Left: 1108 x 1477", font=font, fill=(255, 255, 255))
draw.text((10, left_resized.height + 10), "Right: 1108 x 1477", font=font, fill=(255, 255, 255))
draw.text((10, left_resized.height + right_resized.height + 10), "Panorama: 1775 x 1369", font=font, fill=(255, 255, 255))

# Save the canvas
canvas.save("result/quiz3/agent/run_c1e285578d/comparison.png")
