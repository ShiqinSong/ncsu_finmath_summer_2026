#!/usr/bin/env python
# coding: utf-8

# In[4]:


import numpy as np
import matplotlib.pyplot as plt


N = 300
x_min, x_max = -1.0, 1.0
x = np.linspace(x_min, x_max, N)
dx = x[1] - x[0]

sigma = 0.4
omega = 1.5
tol = 1e-8
max_iter = 20000

# PDE
f = -1.0 * np.ones(N)

A = np.zeros((N, N))
b = np.zeros(N)

coef = -0.5 * sigma**2 / dx**2

for i in range(1, N - 1):
    A[i, i - 1] = coef
    A[i, i] = -2 * coef
    A[i, i + 1] = coef
    b[i] = f[i]

A[0, 0] = 1.0
A[-1, -1] = 1.0
b[0] = -10.0
b[-1] = -10.0

V_unconstrained = np.linalg.solve(A, b)


obstacle = V_unconstrained - 0.8 + 1.2 * np.exp(-20 * x**2)

left_bc = max(V_unconstrained[0], obstacle[0])
right_bc = max(V_unconstrained[-1], obstacle[-1])

V_unconstrained[0] = left_bc
V_unconstrained[-1] = right_bc

V = np.maximum(V_unconstrained.copy(), obstacle)
V[0] = left_bc
V[-1] = right_bc

for it in range(max_iter):
    V_old = V.copy()

    for i in range(1, N - 1):
        V_gs = (
            b[i]
            - A[i, i - 1] * V[i - 1]
            - A[i, i + 1] * V[i + 1]
        ) / A[i, i]

        V_sor = (1 - omega) * V[i] + omega * V_gs

        # Projection step: enforce V >= obstacle
        V[i] = max(obstacle[i], V_sor)

    error = np.max(np.abs(V - V_old))

    if error < tol:
        print(f"Projected SOR converged in {it + 1} iterations.")
        break
else:
    print("Projected SOR did not converge within max_iter.")


contact = np.isclose(V, obstacle, atol=1e-4)
non_contact = ~contact


plt.figure(figsize=(10, 6))

plt.plot(
    x,
    V_unconstrained,
    label="Unconstrained classical solution",
    linewidth=2,
)

plt.plot(
    x,
    obstacle,
    label="Obstacle function g(x)",
    linewidth=2,
)

plt.plot(
    x,
    V,
    label="Projected SOR obstacle solution",
    linewidth=2,
)

plt.scatter(
    x[contact],
    V[contact],
    s=12,
    label="Contact region",
)

plt.xlabel("x")
plt.ylabel("Value")
plt.title("Obstacle Problem Solved by Projected SOR")
plt.legend()
plt.grid(True)
plt.tight_layout()
plt.show()


residual = np.zeros(N)

for i in range(1, N - 1):
    V_xx = (V[i - 1] - 2 * V[i] + V[i + 1]) / dx**2
    residual[i] = -0.5 * sigma**2 * V_xx - f[i]

print("Minimum value of V - obstacle:", np.min(V - obstacle))
print("Number of contact points:", np.sum(contact))
print("Number of non-contact points:", np.sum(non_contact))

if np.any(non_contact):
    print(
        "Maximum PDE residual away from contact region:",
        np.max(np.abs(residual[non_contact])),
    )
else:
    print("Maximum PDE residual away from contact region: no non-contact points.")


print("\nInterpretation:")
print("The unconstrained classical solution solves the PDE without enforcing V >= g.")
print("The projected SOR solution enforces the obstacle constraint at every grid point.")
print("The constrained solution coincides with the obstacle in the contact region.")
print("Away from the contact region, the solution satisfies the PDE approximately.")
print("The boundary between contact and non-contact regions is the free boundary.")
print("At this free boundary, classical smoothness may fail.")
print("This motivates viscosity or variational inequality solutions.")


# In[ ]:




