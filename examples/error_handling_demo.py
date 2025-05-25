"""
Error Handling Demo for Satin
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.append(str(Path(__file__).parent.parent))

from main.error_handling import (
    SatinError, 
    RetryableError,
    ValidationError,
    error_handler,
    retry_on_error,
    handle_error
)

def demo_basic_error_handling():
    """Demonstrate basic error handling"""
    print("=== Basic Error Handling ===")
    
    try:
        raise SatinError("Something went wrong", code=400)
    except SatinError as e:
        result = handle_error(e)
        print(f"Handled error: {result}")

@error_handler()
def demo_decorator_error_handling():
    """Demonstrate error handling with decorator"""
    print("\n=== Decorator Error Handling ===")
    raise ValidationError("Invalid input", field="username")

@retry_on_error(max_retries=3, backoff_factor=0.5)
def demo_retry_mechanism(attempt: int):
    """Demonstrate retry mechanism"""
    print(f"Attempt {attempt}: Processing...")
    if attempt < 2:  # Will fail twice before succeeding
        raise RetryableError("Temporary failure", retry_after=1)
    return "Success!"

def demo_custom_error_handling():
    """Demonstrate custom error handling"""
    print("\n=== Custom Error Handling ===")
    
    def handle_custom_error(error):
        print(f"Custom handler caught: {error}")
        return {"status": "recovered", "message": str(error)}
    
    try:
        raise SatinError("Custom error")
    except SatinError as e:
        result = handle_custom_error(e)
        print(f"Custom handler result: {result}")

def main():
    """Run all demos"""
    demo_basic_error_handling()
    demo_decorator_error_handling()
    
    print("\n=== Retry Mechanism ===")
    try:
        result = demo_retry_mechanism(1)
        print(f"Final result: {result}")
    except Exception as e:
        print(f"Failed after retries: {e}")
    
    demo_custom_error_handling()

if __name__ == "__main__":
    main()
