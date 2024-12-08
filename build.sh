#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Set variables
REGISTRY_HOST=${REGISTRY_HOST:-"192.168.1.221"}
REGISTRY_PORT=${REGISTRY_PORT:-"5001"}
REGISTRY="${REGISTRY_HOST}:${REGISTRY_PORT}"
IMAGE_NAME="kafka-timescale-ingestor"
FULL_IMAGE_NAME="${REGISTRY}/${IMAGE_NAME}"
VERSION_FILE="./src/version.py"

# Error handling
set -e
trap 'echo -e "${RED}Error: Command failed at line $LINENO${NC}"' ERR

# Function to verify docker image
verify_docker_image() {
    local image_tag=$1
    echo -e "${YELLOW}Verifying image: ${image_tag}${NC}"
    
    if ! docker image inspect "${image_tag}" >/dev/null 2>&1; then
        echo -e "${RED}Error: Image ${image_tag} not found locally${NC}"
        return 1
    fi
    
    local size=$(docker image inspect "${image_tag}" --format='{{.Size}}')
    local size_mb=$((size/1024/1024))
    echo -e "${GREEN}Local image size: ${size_mb}MB${NC}"
    
    if [ "$size" -eq 0 ]; then
        echo -e "${RED}Error: Image ${image_tag} has 0 byte size${NC}"
        return 1
    fi
    
    return 0
}

# Function to push with retry
push_with_retry() {
    local image_tag=$1
    local max_retries=3
    local retry_count=0
    
    while [ $retry_count -lt $max_retries ]; do
        echo -e "${YELLOW}Pushing ${image_tag} (Attempt $((retry_count + 1))/${max_retries})${NC}"
        
        if docker push "${image_tag}" 2>&1 | tee /tmp/push_output.log; then
            echo -e "${GREEN}Successfully pushed ${image_tag}${NC}"
            return 0
        fi
        
        echo -e "${RED}Push failed. Error output:${NC}"
        cat /tmp/push_output.log
        
        retry_count=$((retry_count + 1))
        if [ $retry_count -lt $max_retries ]; then
            echo "Waiting 10 seconds before retry..."
            sleep 10
        fi
    done
    
    echo -e "${RED}Failed to push after ${max_retries} attempts${NC}"
    return 1
}

# Function to increment version
increment_version() {
    local version=$1
    local update_type=$2
    local major minor patch

    IFS='.' read -r major minor patch <<< "$version"
    case $update_type in
        major)
            echo "$((major + 1)).0.0"
            ;;
        minor)
            echo "${major}.$((minor + 1)).0"
            ;;
        patch)
            echo "${major}.${minor}.$((patch + 1))"
            ;;
    esac
}

# Create or read version file
if [[ ! -f "$VERSION_FILE" ]]; then
    mkdir -p $(dirname "$VERSION_FILE")
    echo "VERSION = '1.0.0'" > "$VERSION_FILE"
    echo -e "${YELLOW}Created initial version file${NC}"
fi

current_version=$(grep -E "VERSION = '([0-9]+\.[0-9]+\.[0-9]+)'" "$VERSION_FILE" | sed -E "s/VERSION = '(.*)'/\1/")

# Ask if version should be updated
echo -e "${YELLOW}Current version: $current_version${NC}"
read -p "Do you want to update the version? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Select version increment type:"
    echo "1) Major (x.0.0)"
    echo "2) Minor (0.x.0)"
    echo "3) Patch (0.0.x)"
    read -r choice
    
    case $choice in
        1) new_version=$(increment_version "$current_version" "major");;
        2) new_version=$(increment_version "$current_version" "minor");;
        3) new_version=$(increment_version "$current_version" "patch");;
        *) echo -e "${RED}Invalid choice${NC}"; exit 1;;
    esac
    
    echo -e "${GREEN}New version will be: $new_version${NC}"
    read -p "Proceed? (y/n) " -r confirm
    if [[ "$confirm" =~ ^[Yy]$ ]]; then
        echo "VERSION = '$new_version'" > "$VERSION_FILE"
    else
        new_version=$current_version
        echo "Keeping version $current_version"
    fi
else
    new_version=$current_version
fi

# Set image tags
VERSION_TAG="${FULL_IMAGE_NAME}:${new_version}"
LATEST_TAG="${FULL_IMAGE_NAME}:latest"

# Test registry connectivity
echo -e "${YELLOW}Testing registry connectivity...${NC}"
if ! curl -k -f "https://${REGISTRY}/v2/_catalog" >/dev/null 2>&1; then
    echo -e "${RED}Cannot connect to registry at ${REGISTRY}${NC}"
    exit 1
fi

# Build the image
echo -e "${YELLOW}Building image ${VERSION_TAG}${NC}"
if ! docker build --no-cache -t "${VERSION_TAG}" -t "${LATEST_TAG}" .; then
    echo -e "${RED}Build failed${NC}"
    exit 1
fi

# Verify local images
verify_docker_image "${VERSION_TAG}"
verify_docker_image "${LATEST_TAG}"

# Push images with retry logic
if ! push_with_retry "${VERSION_TAG}"; then
    echo -e "${RED}Failed to push version tag${NC}"
    exit 1
fi

if ! push_with_retry "${LATEST_TAG}"; then
    echo -e "${RED}Failed to push latest tag${NC}"
    exit 1
fi

# Verify remote image
echo -e "${YELLOW}Verifying remote image...${NC}"
docker rmi "${VERSION_TAG}" "${LATEST_TAG}"
if ! docker pull "${VERSION_TAG}"; then
    echo -e "${RED}Failed to verify remote image${NC}"
    exit 1
fi

verify_docker_image "${VERSION_TAG}"

echo -e "${GREEN}Successfully built and pushed version ${new_version}${NC}" 