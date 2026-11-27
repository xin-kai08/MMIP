from PIL import Image, ImageDraw, ImageFont

# Load images
left_img = Image.open('data/quiz2/set1/left.jpg').resize((1108, 1477))
right_img = Image.open('data/quiz2/set1/right.jpg').resize((1108, 1477))
panorama_img = Image.open('result/quiz3/agent/run_eb9f0c2583/panorama_ecdffa96.png').resize((1774, 1368))

# Create a new canvas
canvas = Image.new('RGB', (1774, 1368), color='white')
draw = ImageDraw.Draw(canvas)

# Paste images onto the canvas
canvas.paste(left_img, (0, 0))
canvas.paste(right_img, (1108, 0))
canvas.paste(panorama_img, (0, 1477))

# Add labels
draw.text((0, 0), 'Left', font=ImageFont.truetype('arial.ttf', 30), fill='black')
draw.text((1108, 0), 'Right', font=ImageFont.truetype('arial.ttf', 30), fill='black')
draw.text((0, 1477), 'Panorama', font=ImageFont.truetype('arial.ttf', 30), fill='black')

# Save the canvas as a PNG
canvas.save('result/quiz3/agent/run_eb9f0c2583/comparison.png')
