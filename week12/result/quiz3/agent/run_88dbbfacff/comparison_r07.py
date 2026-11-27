from PIL import Image, ImageDraw, ImageFont

# Open the images
left_image = Image.open("data/quiz2/set1/left.jpg")
right_image = Image.open("data/quiz2/set1/right.jpg")
panorama_image = Image.open("result/quiz3/agent/run_88dbbfacff/panorama_30f9f962.png")

# Resize to thumbnail size (420, 420)
left_thumbnail = left_image.thumbnail((420, 420))
right_thumbnail = right_image.thumbnail((420, 420))
panorama_thumbnail = panorama_image.thumbnail((420, 420))

# Create an RGB canvas with room for captions
canvas_width = max(left_thumbnail.width, right_thumbnail.width, panorama_thumbnail.width) + 100
canvas_height = max(left_thumbnail.height, right_thumbnail.height, panorama_thumbnail.height) + 100
canvas = Image.new('RGB', (canvas_width, canvas_height), 'white')

# Paste the images into the canvas
canvas.paste(left_thumbnail, (50, 50))
canvas.paste(right_thumbnail, (canvas_width - 50 - right_thumbnail.width, 50))
canvas.paste(panorama_thumbnail, (50, canvas_height - 50 - panorama_thumbnail.height))

# Draw the captions
caption_font = ImageFont.load_default(size=22)

draw = ImageDraw.Draw(canvas)
draw.text((50, 50), f"Left: {left_image.size[0]} x {left_image.size[1]}", fill="black", font=caption_font)
draw.text((canvas_width - 50 - right_thumbnail.width, 50), f"Right: {right_image.size[0]} x {right_image.size[1]}", fill="black", font=caption_font)
draw.text((50, canvas_height - 50 - panorama_thumbnail.height), f"Panorama: {panorama_image.size[0]} x {panorama_image.size[1]}", fill="black", font=caption_font)

# Save the canvas
canvas.save("result/quiz3/agent/run_88dbbfacff/comparison.png")
