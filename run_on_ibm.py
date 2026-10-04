"""Run a small piece of Quantum Internet Tycoon on a REAL IBM quantum computer.

Two tiny circuits, 4096 shots each (a few seconds of QPU time in total):
  1. One link:  a Bell pair, then a check that it really is a Bell pair (2 qubits).
  2. Two links: entanglement swapping through a repeater, then a check on the end pair (4 qubits).
The measured fidelity is compared with a perfect simulator and with the game's Werner-state formula.

Setup (once):
  pip install qiskit-ibm-runtime
  export QISKIT_IBM_TOKEN="your IBM Quantum Platform API key"      # never paste it into a chat or commit it
  export QISKIT_IBM_INSTANCE="your instance CRN"                    # optional, if you have several

Run:
  python run_on_ibm.py --fake        # dry run on a simulated IBM device, costs nothing
  python run_on_ibm.py               # real hardware (uses your QPU time)
  python run_on_ibm.py --backend ibm_brisbane --shots 2000
"""
import argparse, json, os, time
from pathlib import Path
from qiskit import QuantumCircuit
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager
from qiskit_aer import AerSimulator
from qiskit_ibm_runtime import SamplerV2, QiskitRuntimeService


def bell_check():
    """One link: make a Bell pair, then undo it. Perfect pair -> always reads 00."""
    qc = QuantumCircuit(2, 2, name="one_link")
    qc.h(0)
    qc.cx(0, 1)
    qc.barrier()
    qc.cx(0, 1)
    qc.h(0)
    qc.measure([0, 1], [0, 1])
    return qc


def swap_check():
    """Two links joined by a repeater. Corrections are applied as controlled gates (deferred
    measurement), so no mid-circuit measurement is needed and it runs on any IBM device."""
    qc = QuantumCircuit(4, 2, name="two_links_swap")
    qc.h(0); qc.cx(0, 1)         # link A-B
    qc.h(2); qc.cx(2, 3)         # link B-C
    qc.barrier()
    qc.cx(1, 2); qc.h(1)         # Bell measurement at the repeater (basis change)
    qc.cx(2, 3); qc.cz(1, 3)     # corrections that depend on the repeater's outcome
    qc.barrier()
    qc.cx(0, 3); qc.h(0)         # check: are the end qubits (0 and 3) a Bell pair?
    qc.measure(0, 0)
    qc.measure(3, 1)
    return qc


def fidelity(counts):
    shots = sum(counts.values())
    return counts.get("00", 0) / shots


def run(backend, circuits, shots):
    pm = generate_preset_pass_manager(backend=backend, optimization_level=1)
    isa = [pm.run(c) for c in circuits]
    for c in isa:
        ops = c.count_ops()
        print(f"  {c.name}: depth {c.depth()}, two-qubit gates {sum(v for k, v in ops.items() if k in ('cz', 'ecr', 'cx'))}")
    job = SamplerV2(mode=backend).run(isa, shots=shots)
    print("  job id:", job.job_id())
    res = job.result()
    return [r.data.c.get_counts() for r in res], job.job_id()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fake", action="store_true", help="simulate an IBM device locally (no account needed)")
    ap.add_argument("--backend", help="IBM backend name, default: least busy")
    ap.add_argument("--shots", type=int, default=4096)
    a = ap.parse_args()

    circuits = [bell_check(), swap_check()]
    ideal = AerSimulator().run(circuits, shots=a.shots).result()
    ideal_f = [fidelity(ideal.get_counts(i)) for i in range(2)]

    if a.fake:
        from qiskit_ibm_runtime.fake_provider import FakeSherbrooke
        backend = FakeSherbrooke()
    else:
        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=os.environ.get("QISKIT_IBM_TOKEN"),
            instance=os.environ.get("QISKIT_IBM_INSTANCE"),
        )
        backend = service.backend(a.backend) if a.backend else service.least_busy(
            operational=True, simulator=False, min_num_qubits=4)
    print("Backend:", backend.name)

    t0 = time.time()
    counts, job_id = run(backend, circuits, a.shots)
    f_bell, f_swap = fidelity(counts[0]), fidelity(counts[1])
    predicted = f_bell * f_bell + (1 - f_bell) ** 2 / 3     # the game's swap formula, fed the measured pair
    print(f"\nPerfect simulator:        one link {ideal_f[0]:.3f}   two links {ideal_f[1]:.3f}")
    print(f"{'Simulated device' if a.fake else 'Real hardware'}:        one link {f_bell:.3f}   two links {f_swap:.3f}")
    print(f"Game formula prediction:  two links {predicted:.3f}  (from the measured one-link fidelity)")
    print(f"Took {time.time() - t0:.0f}s including queue time")

    if not a.fake:
        out = {"backend": backend.name, "shots": a.shots, "bell_fidelity": round(f_bell, 4),
               "swap_fidelity": round(f_swap, 4), "swap_predicted": round(predicted, 4),
               "job_id": job_id, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
        Path(__file__).with_name("hardware_calibration.json").write_text(json.dumps(out, indent=2))
        print("Saved hardware_calibration.json. server.py will show it in the game.")


if __name__ == "__main__":
    main()
