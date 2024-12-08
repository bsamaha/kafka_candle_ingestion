#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Set variables
DOCKERFILE_PATH="./Dockerfile"
IMAGE_NAME="registry.local:5000/kafka-timescale-ingestor"
VERSION_FILE="./src/version.py"

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

# Build and push Docker image
build_and_push() {
    local VERSION=$(date +%Y%m%d-%H%M%S)
    echo -e "${YELLOW}Building Docker image version: $VERSION${NC}"
    
    # Build with platform specification
    docker build --platform linux/amd64 -t "${IMAGE_NAME}:${VERSION}" .
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}Docker build failed${NC}"
        exit 1
    fi
    
    docker tag "${IMAGE_NAME}:${VERSION}" "${IMAGE_NAME}:latest"
    
    # Push to local registry
    docker push "${IMAGE_NAME}:${VERSION}"
    docker push "${IMAGE_NAME}:latest"
    
    echo -e "${GREEN}Docker image built and pushed successfully${NC}"
}

# Build Docker image with specific version tag
docker build -t "${IMAGE_NAME}:${new_version}" .

if [ $? -ne 0 ]; then
    echo -e "${RED}Docker build failed${NC}"
    exit 1
fi

# Tag the image as latest
docker tag "${IMAGE_NAME}:${new_version}" "${IMAGE_NAME}:latest"

# Ask for confirmation before pushing
read -p "Do you want to push the images to local registry? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    # Push both version-specific and latest tags to registry
    echo -e "${YELLOW}Pushing ${IMAGE_NAME}:${new_version}...${NC}"
    docker push "${IMAGE_NAME}:${new_version}"
    
    echo -e "${YELLOW}Pushing ${IMAGE_NAME}:latest...${NC}"
    docker push "${IMAGE_NAME}:latest"
    
    echo -e "${GREEN}Successfully pushed version $new_version and latest tags to registry${NC}"
else
    echo -e "${YELLOW}Images built but not pushed to registry${NC}"
fi

# Function to check git configuration
check_git_config() {
    if ! git config --get user.name > /dev/null || ! git config --get user.email > /dev/null; then
        echo -e "${YELLOW}Git configuration incomplete. Setting temporary values...${NC}"
        git config --local user.name "Build Script"
        git config --local user.email "build@local"
        return 1
    fi
    return 0
}

# Function to handle git operations
handle_git_operations() {
    local new_version=$1
    local git_config_status=0
    
    # Check if we're in a git repository
    if ! git rev-parse --git-dir > /dev/null 2>&1; then
        echo -e "${RED}Not a git repository. Skipping git operations.${NC}"
        return 1
    fi
    
    # Check git configuration
    check_git_config
    git_config_status=$?

    # Attempt git operations
    if git add "$VERSION_FILE" && \
       git commit -m "Bump version to $new_version" && \
       git tag -a "v$new_version" -m "Version $new_version"; then
        
        read -p "Do you want to push the git tag and changes? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            if git push origin "v$new_version" && git push origin HEAD; then
                echo -e "${GREEN}Successfully pushed git tag and changes${NC}"
            else
                echo -e "${RED}Failed to push git changes. Please push manually.${NC}"
                return 1
            fi
        fi
    else
        echo -e "${RED}Git operations failed. Please check your git configuration and permissions.${NC}"
        return 1
    fi

    # Cleanup temporary git config if we set it
    if [ $git_config_status -eq 1 ]; then
        git config --local --unset user.name
        git config --local --unset user.email
    fi

    return 0
}

# Replace the git tag section with:
read -p "Do you want to create a git tag for this version? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    if ! handle_git_operations "$new_version"; then
        echo -e "${YELLOW}Continuing with deployment despite git operation failure...${NC}"
    fi
fi

echo -e "${GREEN}Build process completed for version $new_version${NC}" 