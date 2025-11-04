#!/bin/bash

# Weekly Digest Bot - Auto Installer
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
check_root() {
    if [[ $EUID -eq 0 ]]; then
        log_warning "Running as root is not recommended for Docker. Continuing anyway..."
    fi
}

# Check and install Docker
install_docker() {
    if command -v docker &> /dev/null && command -v docker-compose &> /dev/null; then
        log_success "Docker and Docker Compose are already installed"
        return 0
    fi

    log_info "Docker not found. Installing Docker..."

    # Detect OS
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        # Linux
        curl -fsSL https://get.docker.com -o get-docker.sh
        sh get-docker.sh
        usermod -aG docker $USER
        rm get-docker.sh

        # Install Docker Compose
        if ! command -v docker-compose &> /dev/null; then
            log_info "Installing Docker Compose..."
            curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
            chmod +x /usr/local/bin/docker-compose
        fi

    elif [[ "$OSTYPE" == "darwin"* ]]; then
        # Mac OS
        log_error "Please install Docker Desktop for Mac from https://docs.docker.com/desktop/install/mac-install/"
        exit 1
    else
        log_error "Unsupported OS. Please install Docker manually."
        exit 1
    fi

    log_success "Docker installed successfully"
}

# Clone or update repository
setup_repository() {
    local repo_url="https://github.com/l3-lucky-l3/weekly_digest_bot.git"
    local target_dir="weekly_digest_bot"

    if [ -d "$target_dir" ]; then
        log_info "Updating existing repository..."
        cd "$target_dir"
        git pull origin main
    else
        log_info "Cloning repository..."
        git clone "$repo_url" "$target_dir"
        cd "$target_dir"
    fi
}

# Interactive .env configuration
setup_environment() {
    log_info "Setting up environment configuration..."

    if [ -f ".env" ]; then
        log_warning ".env file already exists. Do you want to overwrite it? (y/N)"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            log_info "Keeping existing .env file"
            return 0
        fi
    fi

    # Copy template
    if [ -f ".env.example" ]; then
        cp .env.example .env
    else
        log_error ".env.example not found!"
        exit 1
    fi

    # Interactive configuration
    echo
    log_info "Let's configure your bot settings:"
    echo

    # BOT_TOKEN
    while true; do
        read -p "Enter your Telegram Bot Token: " bot_token
        if [ -n "$bot_token" ]; then
            sed -i "s/BOT_TOKEN=.*/BOT_TOKEN=$bot_token/" .env
            break
        else
            log_warning "Bot token cannot be empty"
        fi
    done

    # OPENROUTER_API_KEY
    while true; do
        read -p "Enter your OpenRouter API Key: " api_key
        if [ -n "$api_key" ]; then
            sed -i "s/OPENROUTER_API_KEY=.*/OPENROUTER_API_KEY=$api_key/" .env
            break
        else
            log_warning "API key cannot be empty"
        fi
    done

    # MAIN_CHAT_ID
    read -p "Enter your main chat/channel ID (or press Enter to skip): " chat_id
    if [ -n "$chat_id" ]; then
        sed -i "s/MAIN_CHAT_ID=.*/MAIN_CHAT_ID=$chat_id/" .env
    fi

    log_success "Environment configuration completed"
}

# Build and start containers
start_services() {
    log_info "Starting Docker services..."

    # Build and start
    docker-compose up -d --build

    # Wait for services to start
    log_info "Waiting for services to initialize..."
    sleep 10

    # Check if containers are running
    if docker-compose ps | grep -q "Up"; then
        log_success "Services started successfully!"
    else
        log_error "Some services failed to start. Check logs with: docker-compose logs"
        exit 1
    fi
}

# Show final instructions
show_instructions() {
    echo
    log_success "🎉 Weekly Digest Bot installation completed!"
    echo
    echo -e "${BLUE}Next steps:${NC}"
    echo "1. View logs: ${GREEN}docker-compose logs -f telegram-bot${NC}"
    echo "2. Check status: ${GREEN}docker-compose ps${NC}"
    echo "3. Configure topics in Telegram:"
    echo "   - Use ${GREEN}/addtopic${NC} in each topic you want to monitor"
    echo "   - Use ${GREEN}/selectconductortopic${NC} for Monday posts"
    echo "   - Use ${GREEN}/selectanouncestopic${NC} for Friday digest"
    echo
    echo -e "${BLUE}Useful commands:${NC}"
    echo "  Restart bot: ${GREEN}docker-compose restart telegram-bot${NC}"
    echo "  Update bot: ${GREEN}git pull && docker-compose up -d --build${NC}"
    echo "  Stop bot: ${GREEN}docker-compose down${NC}"
    echo
    echo -e "${YELLOW}Don't forget to disable 'Group Privacy Mode' in @BotFather!${NC}"
    echo
}

# Main installation function
main() {
    echo -e "${BLUE}"
    echo "╔══════════════════════════════════════════════════╗"
    echo "║           Weekly Digest Bot Installer            ║"
    echo "║         Automated Setup & Configuration          ║"
    echo "╚══════════════════════════════════════════════════╝"
    echo -e "${NC}"

    # Check prerequisites
    check_root

    # Install Docker if needed
    install_docker

    # Setup repository
    setup_repository

    # Configure environment
    setup_environment

    # Start services
    start_services

    # Show instructions
    show_instructions
}

# Update function
update_bot() {
    log_info "Updating Weekly Digest Bot..."

    if [ ! -d "weekly_digest_bot" ]; then
        log_error "Bot directory not found. Run the installer first."
        exit 1
    fi

    cd "weekly_digest_bot"

    # Pull latest changes
    git pull origin main

    # Rebuild and restart
    docker-compose down
    docker-compose up -d --build

    log_success "Bot updated successfully!"

    # Show status
    echo
    docker-compose ps
}

# Help function
show_help() {
    echo "Weekly Digest Bot - Installation Script"
    echo
    echo "Usage: $0 [command]"
    echo
    echo "Commands:"
    echo "  install    - Install and configure the bot (default)"
    echo "  update     - Update existing installation"
    echo "  help       - Show this help message"
    echo
    echo "Examples:"
    echo "  $0 install    # Full installation"
    echo "  $0 update     # Update existing bot"
    echo
}

# Parse command line arguments
case "${1:-install}" in
    "install")
        main
        ;;
    "update")
        update_bot
        ;;
    "help"|"-h"|"--help")
        show_help
        ;;
    *)
        log_error "Unknown command: $1"
        show_help
        exit 1
        ;;
esac