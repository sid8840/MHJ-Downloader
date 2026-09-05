from PIL import Image

SOURCE = "mhj_logo.png"
OUTPUT = "mhj.ico"

img = Image.open(SOURCE).convert("RGBA")

# Make the source square without distorting the logo.
size = max(img.width, img.height)

canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))

x = (size - img.width) // 2
y = (size - img.height) // 2

canvas.paste(img, (x, y), img)

# Windows multi-resolution ICO.
canvas.save(
    OUTPUT,
    format="ICO",
    sizes=[
        (16, 16),
        (20, 20),
        (24, 24),
        (32, 32),
        (40, 40),
        (48, 48),
        (64, 64),
        (96, 96),
        (128, 128),
        (256, 256),
    ],
)

print(f"Created: {OUTPUT}")