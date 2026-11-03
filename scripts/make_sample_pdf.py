"""Generate samples/thermo-first-law.pdf: a short set of course notes used for end-to-end testing.

    python scripts/make_sample_pdf.py      (requires fpdf2, in the dev dependency group)
"""
from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "samples" / "thermo-first-law.pdf"

SECTIONS = [
    ("1. Systems and State Functions", [
        "A thermodynamic system is the region of space we analyze; everything else is the surroundings. A closed "
        "system exchanges energy but not mass with its surroundings; an open system (control volume) exchanges both.",
        "State functions depend only on the current equilibrium state of the system, not on how it got there. "
        "Internal energy U, enthalpy H, entropy S, pressure P, volume V, and temperature T are state functions. "
        "Heat Q and work W are path functions: their values depend on the process path between two states.",
    ]),
    ("2. The First Law of Thermodynamics", [
        "For a closed system, energy is conserved: Delta U = Q - W, where Q is the heat added TO the system and W is "
        "the work done BY the system on its surroundings. (Some texts use W as work done ON the system and write "
        "Delta U = Q + W; always check the sign convention.)",
        "For a cycle the system returns to its initial state, so Delta U = 0 and the net heat added equals the net "
        "work done: Q_net = W_net.",
    ]),
    ("3. Work in Ideal-Gas Processes", [
        "Boundary work is W = integral of P dV. For an ideal gas PV = nRT (R = 8.314 J/(mol K)).",
        "Isobaric (constant P): W = P (V2 - V1).",
        "Isochoric (constant V): W = 0, so Delta U = Q.",
        "Isothermal (constant T): Delta U = 0 for an ideal gas, and W = nRT ln(V2/V1) = Q.",
        "Adiabatic (Q = 0): P V^gamma = constant with gamma = cp/cv, and W = (P1 V1 - P2 V2)/(gamma - 1) = -Delta U.",
    ]),
    ("4. Enthalpy and Specific Heats", [
        "Enthalpy is defined as H = U + PV. At constant pressure, the heat added equals the change in enthalpy: "
        "Q_p = Delta H.",
        "For an ideal gas: Delta U = n cv Delta T and Delta H = n cp Delta T, with cp - cv = R. For a monatomic "
        "ideal gas cv = (3/2)R and cp = (5/2)R, so gamma = 5/3; for a diatomic gas near room temperature "
        "cv = (5/2)R and gamma = 1.4.",
    ]),
    ("5. Heat Engines and Efficiency", [
        "A heat engine takes heat Q_H from a hot reservoir, does work W, and rejects heat Q_C to a cold reservoir. "
        "Its thermal efficiency is eta = W / Q_H = 1 - Q_C / Q_H.",
        "No engine operating between reservoirs at T_H and T_C (in kelvin) can beat the Carnot efficiency "
        "eta_Carnot = 1 - T_C / T_H. A real automotive engine is typically 25-35% efficient.",
        "The Otto cycle (idealized gasoline engine) consists of: (1) adiabatic compression, (2) constant-volume heat "
        "addition, (3) adiabatic expansion (power stroke), and (4) constant-volume heat rejection. Its efficiency is "
        "eta_Otto = 1 - 1 / r^(gamma - 1), where r = V_max / V_min is the compression ratio.",
    ]),
]

TABLE = [
    ("Process", "Held constant", "Work W", "Heat Q"),
    ("Isobaric", "P", "P(V2 - V1)", "n cp Delta T"),
    ("Isochoric", "V", "0", "n cv Delta T"),
    ("Isothermal", "T", "nRT ln(V2/V1)", "W"),
    ("Adiabatic", "Q = 0", "(P1V1 - P2V2)/(gamma-1)", "0"),
]

EXAMPLE = [
    "Worked example. One mole of an ideal diatomic gas expands isothermally at 300 K from 10 L to 20 L.",
    "Step 1: Isothermal, so Delta U = 0.",
    "Step 2: W = nRT ln(V2/V1) = (1)(8.314)(300) ln(2) = 1729 J.",
    "Step 3: First law: Q = Delta U + W = 1729 J of heat is absorbed.",
    "Common mistake: using V2 - V1 instead of the ratio V2/V1, or forgetting that temperature must be in kelvin.",
]


def build() -> None:
    pdf = FPDF(format="Letter")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(20, 18, 20)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "ME 230 - Lecture Notes: The First Law of Thermodynamics", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "I", 10)
    pdf.cell(0, 6, "Chapter 2 | Week 3", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    for title, paragraphs in SECTIONS:
        pdf.set_font("Helvetica", "B", 13)
        pdf.cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 11)
        for p in paragraphs:
            pdf.multi_cell(0, 6, p, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        if title.startswith("3."):
            pdf.set_font("Helvetica", "B", 10)
            widths = (32, 30, 62, 40)
            for r, row in enumerate(TABLE):
                pdf.set_font("Helvetica", "B" if r == 0 else "", 10)
                for w, cell in zip(widths, row):
                    pdf.cell(w, 7, cell, border=1)
                pdf.ln(7)
            pdf.ln(3)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(0, 9, "6. Worked Example", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 11)
    for line in EXAMPLE:
        pdf.multi_cell(0, 6, line, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"Wrote {OUT} ({pdf.page_no()} pages)")


if __name__ == "__main__":
    build()
