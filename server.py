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
from qiskit_aer.noise import NoiseModel, pauli_error, amplitude_damping_error

SHOTS = 2048       # more shots = steadier measured fidelity
BSM_SUCCESS = 0.90 # target chance a Bell measurement works; sets the detector efficiency below
DET_ETA = BSM_SUCCESS ** 0.5  # each of the 2 photon detectors must click, so eta_det^2 = 0.90
FIBER_DB_PER_KM = 0.2         # photon loss in fiber
MAX_GEN = 8
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


def detection_stage(k):
    """Bell measurement succeeds only if BOTH photons are detected. Each detector is a lossy
    channel (amplitude damping) acting on a photon that is present (|1>). One shot = one event."""
    n = 2 * (k - 1)
    if n == 0:
        return True, None
    qc = QuantumCircuit(n, n)
    for q in range(n):
        qc.x(q)           # photon arrives at the detector
    qc.barrier()
    for q in range(n):
        qc.id(q)          # detector inefficiency (amplitude damping)
    qc.barrier()
    qc.measure(range(n), range(n))
    nm = NoiseModel()
    nm.add_all_qubit_quantum_error(amplitude_damping_error(1 - DET_ETA), ["id"])
    mem = AerSimulator(noise_model=nm).run(qc, shots=1, memory=True).result().get_memory()
    return all(c == "1" for c in mem[0]), qc


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
    ok, dqc = detection_stage(k)
    qc = build(k)
    nm = NoiseModel()
    for i, F in enumerate(fs):
        nm.add_quantum_error(werner_error(F), ["id"], [2 * i + 1])
    sim = AerSimulator(noise_model=nm)
    counts = sim.run(qc, shots=SHOTS).result().get_counts()
    good = sum(v for key, v in counts.items() if key.split()[0] == "00")
    return {
        "ok": ok,
        "detect": str(dqc.draw("text", fold=110)) if dqc else "",
        "fidelity": good / SHOTS,
        "formula": formula_fidelity(fs),
        "links": fs,
        "shots": SHOTS,
        "qubits": 2 * k,
        "ms": round((time.time() - t0) * 1000),
        "circuit": str(qc.draw("text", fold=110)),
    }


class GenLink(BaseModel):
    id: int
    length: float
    attempts: int


class GenReq(BaseModel):
    links: list[GenLink]


@app.post("/api/generate")
def generate(req: GenReq):
    """One tick of link generation. Each link sends photons down its fiber; a photon is a qubit
    in |1> that passes through a lossy channel (amplitude damping, eta = 10^(-0.2*L/10)).
    A photon that survives and is detected heralds a fresh entangled pair on that link."""
    links = req.links[:MAX_GEN]
    m = len(links)
    if m == 0:
        return {"results": [], "qubits": 0, "ms": 0, "circuit": ""}
    t0 = time.time()
    shots = max(1, min(400, max(l.attempts for l in links)))
    qc = QuantumCircuit(m, m)
    nm = NoiseModel()
    etas = []
    for j, l in enumerate(links):
        eta = min(1.0, max(0.0, 10 ** (-FIBER_DB_PER_KM * l.length / 10)))
        etas.append(eta)
        qc.x(j)
        nm.add_quantum_error(amplitude_damping_error(1 - eta), ["id"], [j])
    qc.barrier()
    for j in range(m):
        qc.id(j)
    qc.barrier()
    qc.measure(range(m), range(m))
    mem = AerSimulator(noise_model=nm).run(qc, shots=shots, memory=True).result().get_memory()
    results = []
    for j, l in enumerate(links):
        n = max(1, min(shots, l.attempts))
        hits = sum(1 for t in range(n) if mem[t][-1 - j] == "1")
        results.append({"id": l.id, "length": round(l.length), "eta": etas[j],
                        "attempts": n, "hits": hits, "success": hits > 0})
    return {"results": results, "qubits": m, "ms": round((time.time() - t0) * 1000),
            "circuit": str(qc.draw("text", fold=110))}


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")