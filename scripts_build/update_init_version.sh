VERSION=$(uv version --short)
echo "Project version from uv: $VERSION"
sed -i "s#^__version__ = .*#__version__ = \"$VERSION\"#" jncep/__init__.py
echo "Updated jncep/__init__.py to version $VERSION. Verifying content:"
head -n 1 jncep/__init__.py