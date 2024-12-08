#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Error handling
set -e
trap 'echo -e "${RED}Error: Command failed at line $LINENO${NC}"' ERR

echo -e "${YELLOW}Starting deployment process...${NC}"

# Check if kubectl is installed
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}kubectl is not installed. Please install kubectl first.${NC}"
    exit 1
fi

# Check if docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}docker is not installed. Please install docker first.${NC}"
    exit 1
fi

# Add registry variable at the top
IMAGE_NAME="registry.local:5000/kafka-timescale-ingestor"

# Function to check if namespace exists
check_namespace() {
    if ! kubectl get namespace trading &> /dev/null; then
        echo -e "${YELLOW}Creating trading namespace...${NC}"
        kubectl create namespace trading
    fi
}

# Function to check required secrets
check_secrets() {
    if ! kubectl -n trading get secret timescaledb-service-secrets &> /dev/null; then
        echo -e "${RED}Error: timescaledb-service-secrets not found in trading namespace${NC}"
        echo "Please ensure the TimescaleDB secrets are properly configured"
        exit 1
    fi
}

# Build and push Docker image
build_and_push() {
    local VERSION=$(date +%Y%m%d-%H%M%S)
    echo -e "${YELLOW}Building Docker image version: $VERSION${NC}"
    
    docker build -t "${IMAGE_NAME}:${VERSION}" .
    docker tag "${IMAGE_NAME}:${VERSION}" "${IMAGE_NAME}:latest"
    
    # Push to local registry
    docker push "${IMAGE_NAME}:${VERSION}"
    docker push "${IMAGE_NAME}:latest"
    
    echo -e "${GREEN}Docker image built and pushed successfully${NC}"
}

# Deploy to Kubernetes
deploy() {
    echo -e "${YELLOW}Deploying to Kubernetes...${NC}"
    
    # Apply Kubernetes configurations using kustomize
    kubectl apply -k kubernetes/
    
    echo -e "${YELLOW}Waiting for deployment to be ready...${NC}"
    kubectl -n trading rollout status deployment/kafka-timescale-ingestor
}

# Monitor deployment
monitor() {
    echo -e "${YELLOW}Checking deployment status...${NC}"
    
    echo -e "\n${YELLOW}Pods:${NC}"
    kubectl -n trading get pods
    
    echo -e "\n${YELLOW}Services:${NC}"
    kubectl -n trading get services
    
    echo -e "\n${YELLOW}Recent logs:${NC}"
    POD=$(kubectl -n trading get pods -l app=kafka-timescale-ingestor -o jsonpath="{.items[0].metadata.name}")
    kubectl -n trading logs $POD --tail=50
}

# Add function to check registry access
check_registry() {
    echo -e "${YELLOW}Checking registry access...${NC}"
    if ! curl -s registry.local:5000/v2/_catalog > /dev/null; then
        echo -e "${RED}Cannot access local registry. Please ensure registry.local:5000 is available${NC}"
        exit 1
    fi
}

# Main deployment process
main() {
    echo -e "${YELLOW}Starting deployment process...${NC}"
    
    # Add registry check
    check_registry
    
    # Check prerequisites
    check_namespace
    check_secrets
    
    # Build and deploy
    build_and_push
    deploy
    
    # Monitor deployment
    monitor
    
    echo -e "${GREEN}Deployment completed successfully!${NC}"
}

# Run main function
main

# Add help text if no arguments provided
if [ "$1" == "--help" ]; then
    echo "Usage: ./deploy.sh"
    echo "This script builds and deploys the Kafka-TimescaleDB ingestion service"
    echo ""
    echo "The script will:"
    echo "  1. Check prerequisites (kubectl, docker)"
    echo "  2. Verify namespace and secrets"
    echo "  3. Build and tag Docker image"
    echo "  4. Deploy to Kubernetes using kustomize"
    echo "  5. Monitor deployment status"
    exit 0
fi 