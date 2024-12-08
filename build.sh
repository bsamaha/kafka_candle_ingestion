#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Set variables
DOCKERFILE_PATH="./Dockerfile"
REGISTRY_HOST=${REGISTRY_HOST:-"registry.local"}
REGISTRY_PORT=${REGISTRY_PORT:-"5001"}
IMAGE_NAME="kafka-timescale-ingestor"
FULL_IMAGE_NAME="${REGISTRY_HOST}:${REGISTRY_PORT}/${IMAGE_NAME}"
VERSION_FILE="./src/version.py"
INSECURE_REGISTRY=true  # Set to true if using self-signed certificates

# Error handling
set -e
trap 'echo -e "${RED}Error: Command failed at line $LINENO${NC}"' ERR

# Function to increment version
increment_version() {
    local version=$1
    local update_type=$2
    local major minor patch

    IFS='.' read -r major minor patch <<< "$version"
    case $update_type in
        major)
            major=$((major + 1))
            minor=0
            patch=0
            ;;
        minor)
            minor=$((minor + 1))
            patch=0
            ;;
        patch)
            patch=$((patch + 1))
            ;;
    esac
    echo "$major.$minor.$patch"
}

# Create version.py if it doesn't exist
if [[ ! -f "$VERSION_FILE" ]]; then
    mkdir -p $(dirname "$VERSION_FILE")
    echo "VERSION = '1.0.0'" > "$VERSION_FILE"
    echo -e "${YELLOW}Created initial version file${NC}"
fi

# Ask if version should be updated
read -p "Do you want to update the version? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Read current version from version.py
    current_version=$(grep -E "VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'" "$VERSION_FILE" | sed -E "s/VERSION = '(.*)'/\1/")

    if [[ -z "$current_version" ]]; then
        echo -e "${YELLOW}No valid version found in version.py. Setting initial version to 1.0.0${NC}"
        new_version="1.0.0"
    else
        echo -e "${GREEN}Current version: $current_version${NC}"
        
        # Ask for update type
        while true; do
            read -p "Is this a major, minor, or patch update? " update_type
            case $update_type in
                major|minor|patch) break;;
                *) echo -e "${RED}Please enter 'major', 'minor', or 'patch'.${NC}";;
            esac
        done

        # Increment version
        new_version=$(increment_version "$current_version" "$update_type")
    fi

    # Update version in version.py
    echo "VERSION = '$new_version'" > "$VERSION_FILE"
    echo -e "${YELLOW}Updated to version $new_version${NC}"
else
    # Use current version if it exists, or set to default
    new_version=$(grep -E "VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'" "$VERSION_FILE" 2>/dev/null | sed -E "s/VERSION = '(.*)'/\1/")
    if [[ -z "$new_version" ]]; then
        new_version="1.0.0"
        echo "VERSION = '$new_version'" > "$VERSION_FILE"
    fi
    echo -e "${YELLOW}Keeping current version: $new_version${NC}"
fi

echo -e "${YELLOW}Building version $new_version...${NC}"

# Build Docker image with specific version tag
echo -e "${YELLOW}Building Docker image...${NC}"
if docker build -t "${FULL_IMAGE_NAME}:${new_version}" .; then
    # Tag the image as latest
    docker tag "${FULL_IMAGE_NAME}:${new_version}" "${FULL_IMAGE_NAME}:latest"
    
    # Push both version-specific and latest tags to registry
    echo -e "${YELLOW}Pushing images to registry...${NC}"
    if [ "$INSECURE_REGISTRY" = true ]; then
        DOCKER_OPTS="--insecure-registry registry.local:5001"
        # Configure Docker to accept insecure registry
        if ! grep -q "registry.local:5001" /etc/docker/daemon.json 2>/dev/null; then
            echo -e "${YELLOW}Configuring Docker to accept insecure registry...${NC}"
            sudo mkdir -p /etc/docker
            echo '{
    "insecure-registries" : ["registry.local:5001"]
}' | sudo tee /etc/docker/daemon.json > /dev/null
            sudo systemctl restart docker
        fi
    fi

    if docker $DOCKER_OPTS push "${FULL_IMAGE_NAME}:${new_version}" && \
       docker $DOCKER_OPTS push "${FULL_IMAGE_NAME}:latest"; then
        echo -e "${GREEN}Successfully pushed version ${new_version} and latest tags to registry${NC}"
    else
        echo -e "${RED}Failed to push images to registry${NC}"
        exit 1
    fi
else
    echo -e "${RED}Docker build failed${NC}"
    exit 1
fi

echo -e "${GREEN}Build process completed for version $new_version${NC}" 