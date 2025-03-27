import argparse
import json
import sys

from traefik_validator.utils import Validator, ValidationError


def validate_traefik():
    """
    CLI entry point for validating Traefik configurations.
    
    Parses command-line arguments and runs validation on provided config files.
    """
    parser = argparse.ArgumentParser(prog="validate_traefik", description='Validate traefik config file.')
    parser.add_argument('-s', '--static-config', type=argparse.FileType('r'), help='The static file path')
    parser.add_argument('-d', '--dynamic-config', type=argparse.FileType('r'), help='The dynamic file path')
    parser.add_argument('--offline', action='store_true', help='Use cached schemas without downloading')
    parser.add_argument('--json', action='store_true', help='Output results in JSON format')
    parser.add_argument('--version', action='store_true', help='Show version information')

    args = parser.parse_args()
    
    if args.version:
        from traefik_validator import __version__
        print(f"traefik-validator version {__version__}")
        print(f"Supports Traefik v3.3.3")
        sys.exit(0)

    try:
        # Ensure at least one config file is provided
        if not args.static_config and not args.dynamic_config:
            parser.print_help()
            print("\nError: You must provide at least one configuration file to validate")
            sys.exit(1)
            
        validator = Validator(
            static_conf_file=args.static_config, 
            dynamic_conf_file=args.dynamic_config,
            offline=args.offline
        )
        
        validator.validate()
        
        if args.json:
            print(json.dumps({"success": True, "message": "Configuration is valid"}))
        else:
            print("\n\033[92m✓\033[0m All configurations are valid")
            
    except ValidationError as e:
        if args.json:
            print(json.dumps({"success": False, "message": str(e)}))
        else:
            print(f"\n\033[91m✗\033[0m {e}")
        sys.exit(1)
    except ValueError as e:
        if args.json:
            print(json.dumps({"success": False, "message": str(e)}))
        else:
            print(f"\n\033[91m✗\033[0m Error: {e}")
        sys.exit(1)
    except Exception as e:
        if args.json:
            print(json.dumps({"success": False, "message": f"Unexpected error: {str(e)}"}))
        else:
            print(f"\n\033[91m✗\033[0m Unexpected error: {e}")
        sys.exit(1)