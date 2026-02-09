import inspect
from dhanhq import dhanhq

print("Inspect dhanhq signature:")
try:
    print(inspect.signature(dhanhq.__init__))
except Exception as e:
    print(e)

print("\nInspect dhanhq doc:")
print(dhanhq.__init__.__doc__)
