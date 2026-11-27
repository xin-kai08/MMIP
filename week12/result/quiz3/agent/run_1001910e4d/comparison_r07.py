from PIL import Image, ImageDraw, ImageFont

# Open the images
left_image = Image.open("data/quiz2/set1/left.jpg")
right_image = Image.open("data/quiz2/set1/right.jpg")
panorama_image = Image.open("result/quiz3/agent/run_1001910e4d/panorama_7656088b.png")

# Define the scale factor (example: 0.5)
scale_factor = 0.5

# Resize the images
left_resized = left_image.resize((int(left_image.width * scale_factor), int(left_image.height * scale_factor)))
right_resized = right_image.resize((int(right_image.width * scale_factor), int(right_image.height * scale_factor)))
panorama_resized = panorama_image.resize((int(panorama_image.width * scale_factor), int(panorama_image.height * scale_factor)))

# Define the canvas dimensions based on the row or column
canvas_width = sum(left_resized.width + right_resized.width + 10)  # Example: add 10 pixels for gaps
canvas_height = max(left_resized.height + right_resized.height + 20)  # Example: add 20 pixels for margins and caption space

# Create a new canvas
canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')

# Paste the images onto the canvas
canvas.paste(left_resized, (0, 0))
canvas.paste(right_resized, (left_resized.width, 0))
canvas.paste(panorama_resized, (left_resized.width + right_resized.width, 0))

# Draw the captions
caption_font = ImageFont.load_default(size=22)

canvas.paste(ImageDraw.Draw(canvas).text((10, 10), "Left: 1108 x 1477", font=caption_font), (0, 0))
canvas.paste(ImageDraw.Draw(canvas).text((left_resized.width + 10, 10), "Right: 1108 x 1477", font=caption_font), (left_resized.width, 0))
canvas.paste(ImageDraw.Draw(canvas).text((left_resized.width + right_resized.width + 10, 10), "Panorama: 1779 x 1369", font=caption_font), (left_resized.width + right_resized.width, 0))

# Save the canvas
canvas.save("result/quiz3/agent/run_1001910e4d/comparison.png")
