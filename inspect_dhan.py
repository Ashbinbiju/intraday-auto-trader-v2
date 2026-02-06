from dhanhq import dhanhq
import inspect

print("--- DhanHQ Methods ---")
methods = inspect.getmembers(dhanhq, predicate=inspect.isfunction)
for name, func in methods:
    print(name)

print("\n--- DhanHQ Class Attributes ---")
# Create a dummy instance to check methods if possible (requires creds, so might fail)
# better to check the class object itself
class_methods = [func for func in dir(dhanhq) if callable(getattr(dhanhq, func)) and not func.startswith("__")]
print(class_methods)

print("\n--- Docstring check ---")
# Check if there is a 'connect_websocket' or similar
for m in class_methods:
    if 'socket' in m.lower() or 'ws' in m.lower() or 'feed' in m.lower():
        print(f"Match: {m}")
        print(getattr(dhanhq, m).__doc__)
