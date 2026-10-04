"""Quantum Internet Tycoon backend: runs each repeater-chain delivery as a real Qiskit circuit.

Run:  uvicorn server:app --port 8000   then open http://localhost:8000
"""
import random, time
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from qiskit import QuantumCircuit, QuantumRegister, ClassicalRegister
from qiskit_aer import AerSimulator
from qiskit_aer.noise import NoiseModel, pauli_error

SHOTS = 2048       # more shots = steadier measured fidelity
BSM_SUCCESS = 0.90 # chance each Bell measurement works (imperfect hardware)
MAX_LINKS = 4      # 4 links = 8 qubits

app = FastAPI(title="Quantum Internet Tycoon backend")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def werner_error(F):
    """Noise that turns a perfect Bell pair into a Werner state of fidelity F."""
    q = (1 - F) / 3
    return pauli_error([("I", F), ("X", q), ("Y", q), ("Z", q)])


def build(k):
    """k Bell pairs -> (k-1) entanglement swaps -> fidelity check on the end-to-end pair."""
    n = 2 * k
    q = QuantumRegister(n, "q")
    m = [ClassicalRegister(2, f"m{i}") for i in range(k - 1)]
    f = ClassicalRegister(2, "f")
    qc = QuantumCircuit(q, *m, f)
    for i in range(k):                       # 1. each link makes a Bell pair
        qc.h(2 * i)
        qc.cx(2 * i, 2 * i + 1)
    qc.barrier()
    for i in range(k):                       # 2. noise slot: memory decay / fiber noise
        qc.id(2 * i + 1)
    qc.barrier()
    for i in range(k - 1):                   # 3. repeater: Bell measurement + correction
        a, b, tgt = 2 * i + 1, 2 * i + 2, 2 * i + 3
        qc.cx(a, b)
        qc.h(a)
        qc.measure(a, m[i][0])
        qc.measure(b, m[i][1])
        with qc.if_test((m[i][1], 1)):
            qc.x(tgt)
        with qc.if_test((m[i][0], 1)):
            qc.z(tgt)
    qc.barrier()
    qc.cx(0, n - 1)                          # 4. check: is (first, last) a perfect Bell pair?
    qc.h(0)
    qc.measure(0, f[0])
    qc.measure(n - 1, f[1])
    return qc


def formula_fidelity(fs):
    F = fs[0]
    for x in fs[1:]:
        F = F * x + (1 - F) * (1 - x) / 3
    return F


class Req(BaseModel):
    fidelities: list[float]


@app.get("/api/health")
def health():
    return {"ok": True, "backend": "qiskit-aer", "shots": SHOTS}


@app.post("/api/swap")
def swap(req: Req):
    fs = [min(0.999, max(0.25, x)) for x in req.fidelities][:MAX_LINKS]
    k = len(fs)
    t0 = time.time()
    qc = build(k)
    nm = NoiseModel()
    for i, F in enumerate(fs):
        nm.add_quantum_error(werner_error(F), ["id"], [2 * i + 1])
    sim = AerSimulator(noise_model=nm)
    counts = sim.run(qc, shots=SHOTS).result().get_counts()
    good = sum(v for key, v in counts.items() if key.split()[0] == "00")
    return {
        "ok": all(random.random() < BSM_SUCCESS for _ in range(k - 1)),
        "fidelity": good / SHOTS,
        "formula": formula_fidelity(fs),
        "links": fs,
        "shots": SHOTS,
        "qubits": 2 * k,
        "ms": round((time.time() - t0) * 1000),
        "circuit": str(qc.draw("text", fold=110)),
    }


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")
