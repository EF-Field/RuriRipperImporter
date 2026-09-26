"""Branch-local entrypoint: always package the Blender 5.2 legacy addon."""
from package_blender52 import build

if __name__ == '__main__':
    build()
