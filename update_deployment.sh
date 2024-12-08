#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Set variables
IMAGE_NAME="registry.local:5000/kafka-timescale-ingestor"
NAMESPACE="trading"
DEPLOYMENT_NAME="kafka-timescale-ingestor"
CONTAINER_NAME="ingestor"

# Error handling
set -e
trap 'echo -e "${RED}Error: Command failed at line $LINENO${NC}"' ERR

# Function to check if kubectl is available
check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        echo -e "${RED}kubectl is not installed or not in PATH${NC}"
        exit 1
    fi
}

# Function to check if namespace exists
check_namespace() {
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
        echo -e "${RED}Namespace $NAMESPACE does not exist${NC}"
        exit 1
    fi
}

# Function to check if deployment exists
check_deployment() {
    if ! kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT_NAME" &> /dev/null; then
        echo -e "${RED}Deployment $DEPLOYMENT_NAME does not exist in namespace $NAMESPACE${NC}"
        exit 1
    fi
}

# Function to get current version
get_current_version() {
    local current_image
    current_image=$(kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT_NAME" -o jsonpath="{.spec.template.spec.containers[?(@.name=='$CONTAINER_NAME')].image}")
    echo "$current_image"
}

# Perform initial checks
check_kubectl
check_namespace
check_deployment

# Get current version
current_image=$(get_current_version)
echo -e "${GREEN}Current image: $current_image${NC}"

# Ask for version to deploy
read -p "Enter the version to deploy (or 'latest'): " VERSION
if [[ -z "$VERSION" ]]; then
    echo -e "${RED}Version cannot be empty${NC}"
    exit 1
fi

# Construct new image tag
NEW_IMAGE="${IMAGE_NAME}:${VERSION}"

# Confirm deployment
echo -e "${YELLOW}About to update deployment:${NC}"
echo "Namespace: $NAMESPACE"
echo "Deployment: $DEPLOYMENT_NAME"
echo "New image: $NEW_IMAGE"
read -p "Continue? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Deployment cancelled${NC}"
    exit 0
fi

# Update the deployment
echo -e "${YELLOW}Updating deployment...${NC}"
if kubectl -n "$NAMESPACE" set image deployment/"$DEPLOYMENT_NAME" \
    "$CONTAINER_NAME=$NEW_IMAGE"; then
    echo -e "${GREEN}Deployment image updated successfully${NC}"
else
    echo -e "${RED}Failed to update deployment image${NC}"
    exit 1
fi

# Watch the rollout
echo -e "${YELLOW}Watching rollout status...${NC}"
if kubectl -n "$NAMESPACE" rollout status deployment/"$DEPLOYMENT_NAME"; then
    echo -e "${GREEN}Rollout completed successfully${NC}"
else
    echo -e "${RED}Rollout failed${NC}"
    echo -e "${YELLOW}Checking pod status...${NC}"
    kubectl -n "$NAMESPACE" get pods | grep "$DEPLOYMENT_NAME"
    exit 1
fi

# Show deployment status
echo -e "\n${YELLOW}Current deployment status:${NC}"
kubectl -n "$NAMESPACE" get deployment "$DEPLOYMENT_NAME"

# Show pods status
echo -e "\n${YELLOW}Pod status:${NC}"
kubectl -n "$NAMESPACE" get pods | grep "$DEPLOYMENT_NAME" 