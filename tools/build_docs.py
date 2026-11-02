"""Build the synthetic equipment manuals and SOPs used as the RAG corpus.

All equipment, brands and procedures are fictional (Northgate Equipment Co.,
Northgate Distribution). Fault codes and operating ranges match the telemetry
generator in src/ingest/02_generate_telemetry.py, so answers can be checked.

Usage:  python tools/build_docs.py  -> writes PDFs to data/docs/
"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether, ListFlowable, ListItem, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT = Path(__file__).resolve().parents[1] / "data" / "docs"

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=16, spaceAfter=8, textColor=colors.HexColor("#1F3864"))
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=6, textColor=colors.HexColor("#1F3864"))
H3 = ParagraphStyle("H3", parent=ss["Heading3"], fontSize=11, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("Body", parent=ss["BodyText"], fontSize=10, leading=13.5, alignment=TA_LEFT, spaceAfter=6)
SMALL = ParagraphStyle("Small", parent=BODY, fontSize=8.5, leading=11)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=9, leading=11.5, spaceAfter=0)
WARN = ParagraphStyle("Warn", parent=BODY, backColor=colors.HexColor("#FFF4CE"), borderPadding=6,
                      borderColor=colors.HexColor("#C9A400"), borderWidth=0.5, spaceBefore=6, spaceAfter=10)


def table(rows, widths):
    data = [[Paragraph(str(c), CELL) for c in r] for r in rows]
    t = Table(data, colWidths=[w * inch for w in widths], repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D9E2F3")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#8EA9DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def steps(items):
    return ListFlowable([ListItem(Paragraph(i, BODY), leftIndent=12) for i in items],
                        bulletType="1", leftIndent=14, bulletFontSize=9)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(i, BODY), leftIndent=12) for i in items],
                        bulletType="bullet", start="•", leftIndent=14, bulletFontSize=8)


def header_block(doc_no, title, rev, date, owner):
    return [
        Paragraph(title, H1),
        table([["Document", "Revision", "Effective", "Owner"], [doc_no, rev, date, owner]], [1.8, 0.9, 1.3, 2.5]),
        Spacer(1, 10),
    ]


def build(filename, doc_no, title, story_fn, rev="C", date="2025-03-01", owner="Northgate Equipment Co."):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / filename

    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(0.75 * inch, 0.5 * inch, f"{doc_no}  Rev {rev}  |  {title}")
        canvas.drawRightString(7.75 * inch, 0.5 * inch, f"Page {doc.page}")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=LETTER, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.75 * inch, bottomMargin=0.8 * inch, title=title, author=owner)
    story = header_block(doc_no, title, rev, date, owner) + story_fn()
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return path


def fault_section(faults):
    """faults: list of dicts with code, name, trigger, severity, causes, actions."""
    out = [Paragraph("Fault Code Reference", H2),
           table([["Code", "Name", "Trigger condition", "Severity"]] +
                 [[f["code"], f["name"], f["trigger"], f["severity"]] for f in faults],
                 [0.6, 1.7, 3.0, 0.9]),
           Paragraph("Troubleshooting by Fault Code", H2)]
    for f in faults:
        block = [Paragraph(f"{f['code']}: {f['name']}", H3),
                 Paragraph(f"<b>Trigger:</b> {f['trigger']}", BODY),
                 Paragraph("<b>Likely causes, most common first:</b>", BODY), bullets(f["causes"]),
                 Paragraph("<b>Corrective actions:</b>", BODY), steps(f["actions"])]
        if f.get("note"):
            block.append(Paragraph(f["note"], WARN))
        out.append(KeepTogether(block[:3]))
        out.extend(block[3:])
    return out


LOTO_NOTE = ("<b>WARNING:</b> Apply lockout/tagout per SOP-OPS-001 before opening any electrical "
             "enclosure or touching moving parts. Only authorized technicians may perform these steps.")

# --------------------------------------------------------------------------------------------
# Manual 1: CU-400 condensing unit
# --------------------------------------------------------------------------------------------

def cu400():
    s = [
        Paragraph("1. Overview", H2),
        Paragraph("The Northgate CU-400 is an air-cooled, semi-hermetic condensing unit for walk-in coolers "
                  "from 800 to 2,400 cu ft. It runs on R-448A and holds box temperatures between 33F and 40F. "
                  "The unit reports box temperature, head (discharge) pressure, power draw and cabinet vibration "
                  "to the site monitoring system every 15 minutes.", BODY),
        Paragraph("2. Specifications", H2),
        table([["Item", "Value"],
               ["Refrigerant", "R-448A, 14 lb factory charge"],
               ["Compressor", "Semi-hermetic reciprocating, 4 HP"],
               ["Electrical", "208-230V / 3 ph / 60 Hz, MCA 22 A, MOPD 35 A"],
               ["Condenser", "Copper tube, aluminum fin, 2 x 18 in fans, 1,075 rpm"],
               ["Rated capacity", "28,500 BTU/h at 25F SST, 95F ambient"],
               ["Max ambient", "115F"],
               ["Weight", "385 lb"]], [2.0, 4.5]),
        Paragraph("3. Normal Operating Ranges", H2),
        Paragraph("Readings outside these ranges for more than 30 minutes need attention, even if no fault code is active.", BODY),
        table([["Measurement", "Normal range", "Alarm limit"],
               ["Box temperature", "34F to 38F", "Above 41F for 30 min (E-42)"],
               ["Head pressure", "220 to 280 psig", "Above 300 psig for 10 min (E-21)"],
               ["Power draw", "3.8 to 4.6 kW", "Above 6.0 kW (E-30)"],
               ["Cabinet vibration", "Below 3.0 mm/s RMS", "Above 5.0 mm/s"]], [1.8, 1.9, 2.8]),
        PageBreak(),
    ]
    s += fault_section([
        dict(code="E-21", name="High head pressure", severity="High",
             trigger="Head pressure above 300 psig for 10 consecutive minutes. Unit stops the compressor at 395 psig (high-pressure switch).",
             causes=["Dirty or blocked condenser coil. This causes about 70% of E-21 events, especially at hot or dusty sites.",
                     "Failed condenser fan motor or seized fan blade.",
                     "Recirculation of hot discharge air because of blocked clearance (needs 24 in on all sides).",
                     "Refrigerant overcharge after recent service.",
                     "Non-condensable gas in the system."],
             actions=["Check that both condenser fans run. A fan that is off with the compressor running points to a failed fan motor or capacitor.",
                      "Inspect the condenser coil. If dirty, apply LOTO and clean with coil cleaner and low-pressure water from the inside out.",
                      "Confirm 24 in clearance around the unit and remove debris, pallets or shrink wrap.",
                      "If pressure stays above 300 psig after cleaning, compare subcooling to the 10F to 14F target. High subcooling means overcharge.",
                      "Log readings before and after in the work order. If the box temperature has risen above 41F, start SOP-OPS-002."],
             note="Rising box temperature together with E-21 means the unit is losing capacity. Treat it as a P1 event under SOP-OPS-003."),
        dict(code="E-14", name="Low suction pressure", severity="Medium",
             trigger="Suction pressure below 18 psig for 15 minutes.",
             causes=["Iced evaporator coil.", "Low refrigerant charge or leak.", "Restricted filter drier."],
             actions=["Check the evaporator for ice and run a manual defrost.", "Leak test with an electronic detector.",
                      "Measure pressure drop across the filter drier. Replace if above 3 psi."]),
        dict(code="E-30", name="Compressor overload trip", severity="High",
             trigger="Power draw above 6.0 kW, or the internal overload opens.",
             causes=["High head pressure (see E-21).", "Low supply voltage (below 197V).", "Failing compressor valves."],
             actions=["Measure supply voltage on all three legs. Imbalance above 2% needs an electrician.",
                      "Clear any E-21 condition first, then reset.", "If E-30 repeats within 24 hours, open a P2 work order for compressor diagnosis."]),
        dict(code="E-42", name="High box temperature", severity="High",
             trigger="Box temperature above 41F for 30 consecutive minutes.",
             causes=["Door left open or damaged door gasket.", "Any active E-21, E-14 or E-30 fault.", "Product loaded warm."],
             actions=["Check the door and strip curtain.", "Resolve any other active fault code.",
                      "Start SOP-OPS-002 Cold Chain Temperature Excursion Response."]),
    ])
    s += [
        Paragraph("Preventive Maintenance", H2),
        table([["Task", "Interval"],
               ["Clean condenser coil", "Quarterly. Monthly at Lakeland and Stockton sites (see SOP-OPS-004)."],
               ["Check fan motors and blades", "Quarterly"],
               ["Check refrigerant charge and subcooling", "Semi-annually"],
               ["Tighten electrical connections", "Annually"]], [3.0, 3.5]),
        Paragraph(LOTO_NOTE, WARN),
    ]
    return s

# --------------------------------------------------------------------------------------------
# Manual 2: EV-220 freezer evaporator
# --------------------------------------------------------------------------------------------

def ev220():
    s = [
        Paragraph("1. Overview", H2),
        Paragraph("The Northgate EV-220 is a low-profile electric-defrost evaporator for walk-in and warehouse freezers. "
                  "It holds box temperatures between -15F and -5F. Defrost runs on a timer, 4 times per day by default, "
                  "and ends on coil temperature (50F) or after a 45 minute fail-safe.", BODY),
        Paragraph("2. Specifications", H2),
        table([["Item", "Value"],
               ["Capacity", "22,000 BTU/h at -20F SST, 10F TD"],
               ["Fans", "3 x 16 in ECM motors, 230V / 1 ph"],
               ["Defrost heaters", "4.8 kW total, electric"],
               ["Drain line heater", "Self-regulating, 8 W/ft"],
               ["Power draw, normal", "1.5 to 2.2 kW (fans and controls); 6.5 kW during defrost"]], [2.0, 4.5]),
        Paragraph("3. Normal Operating Ranges", H2),
        table([["Measurement", "Normal range", "Alarm limit"],
               ["Box temperature", "-15F to -5F", "Above 0F for 30 min (F-20)"],
               ["Suction pressure", "15 to 25 psig", "Below 10 psig"],
               ["Defrost duration", "18 to 30 min", "Over 45 min (DF-4)"],
               ["Fan vibration", "Below 2.0 mm/s", "Above 4.0 mm/s"]], [1.8, 1.9, 2.8]),
        Paragraph("A box temperature that climbs during the night defrost window and keeps climbing after "
                  "the window ends usually means a defrost that did not terminate. Check for DF-4.", BODY),
        PageBreak(),
    ]
    s += fault_section([
        dict(code="DF-4", name="Defrost termination failure", severity="High",
             trigger="Defrost runs past the 45 minute fail-safe, or the coil sensor never reaches 50F.",
             causes=["Failed defrost termination sensor (most common).", "Defrost contactor stuck closed.",
                     "Controller clock or schedule fault after a power loss."],
             actions=["Check the controller display. If it shows DEFROST more than 45 minutes after the start, force the unit back to cooling.",
                      "Measure the termination sensor resistance. It should read 10k ohm at 77F. Replace if open or shorted.",
                      "Check the defrost contactor. If the contacts are welded, replace the contactor.",
                      "Watch the next scheduled defrost to confirm it ends between 18 and 30 minutes.",
                      "If box temperature went above 0F, start SOP-OPS-002."],
             note="Heaters left on during a failed defrost can raise box temperature by 20F or more in 3 hours."),
        dict(code="F-11", name="Evaporator fan failure", severity="Medium",
             trigger="One or more fans draw under 0.2 A while commanded on.",
             causes=["Failed ECM motor.", "Ice on fan blade.", "Loose plug at motor harness."],
             actions=["Look for ice on the fan guard and run a manual defrost.", "Check the harness plug.", "Replace the motor if it does not start with 230V present."]),
        dict(code="F-20", name="High box temperature", severity="High",
             trigger="Box temperature above 0F for 30 consecutive minutes.",
             causes=["Active DF-4 or F-11.", "Door held open during loading.", "Iced coil."],
             actions=["Resolve any other active fault.", "Close doors and check strip curtains.",
                      "Start SOP-OPS-002. Freezer product above 10F for more than 60 minutes must be quarantined."]),
        dict(code="F-31", name="Drain line heater fault", severity="Low",
             trigger="Drain heater current below 0.1 A.",
             causes=["Open heater cable.", "Tripped GFCI."],
             actions=["Reset the GFCI.", "Replace the heater cable if open. Check for ice in the drain pan."]),
    ])
    s += [Paragraph("Preventive Maintenance", H2),
          table([["Task", "Interval"],
                 ["Inspect coil for ice pattern", "Monthly"],
                 ["Test defrost termination sensor", "Quarterly"],
                 ["Check drain line heater", "Before winter, then quarterly"],
                 ["Clean fan blades and guards", "Semi-annually"]], [3.0, 3.5]),
          Paragraph(LOTO_NOTE, WARN)]
    return s

# --------------------------------------------------------------------------------------------
# Manual 3: AC-75 air compressor
# --------------------------------------------------------------------------------------------

def ac75():
    s = [
        Paragraph("1. Overview", H2),
        Paragraph("The Northgate AC-75 is a 75 HP oil-flooded rotary screw air compressor. It supplies plant air for "
                  "conveyor diverters, palletizers and dock equipment. The controller reports discharge temperature, "
                  "line pressure, power draw and airend vibration.", BODY),
        Paragraph("2. Specifications", H2),
        table([["Item", "Value"],
               ["Motor", "75 HP, 460V / 3 ph, TEFC"],
               ["Free air delivery", "322 CFM at 125 psig"],
               ["Pressure setpoint", "125 psig, load/unload band 115 to 135 psig"],
               ["Lubricant", "Northgate SynLube 8000, 9 gal"],
               ["Bearings", "Airend: tapered roller; motor: 6316 drive end, 6313 non-drive end"]], [2.0, 4.5]),
        Paragraph("3. Normal Operating Ranges", H2),
        table([["Measurement", "Normal range", "Alarm limit"],
               ["Discharge temperature", "165F to 195F", "Above 220F (T-05), shutdown at 230F"],
               ["Line pressure", "115 to 135 psig", "Below 100 psig"],
               ["Power draw", "48 to 60 kW loaded", "Above 68 kW"],
               ["Airend vibration", "Below 4.5 mm/s RMS", "4.5 mm/s alert (V-02), 7.1 mm/s alarm (V-03)"]], [1.8, 1.9, 2.8]),
        Paragraph("Vibration limits follow ISO 10816-3 for medium machines on rigid foundations. A steady rise over days "
                  "is more important than a single high reading. Trend vibration weekly.", BODY),
        PageBreak(),
    ]
    s += fault_section([
        dict(code="V-02", name="Vibration alert", severity="Medium",
             trigger="Airend vibration above 4.5 mm/s RMS for 1 hour.",
             causes=["Early bearing wear.", "Coupling misalignment after maintenance.", "Loose mounting bolts."],
             actions=["Check mounting bolt torque (85 ft-lb).", "Check coupling alignment with a laser tool. Limit is 0.002 in offset.",
                      "Take an oil sample for wear-metal analysis.", "Increase vibration readings to daily until the trend is flat."]),
        dict(code="V-03", name="Vibration alarm", severity="High",
             trigger="Airend vibration above 7.1 mm/s RMS.",
             causes=["Advanced bearing wear (most common when vibration rose steadily over 1 to 2 weeks).",
                     "Severe misalignment.", "Rotor contact inside the airend."],
             actions=["Plan a controlled shutdown within 24 hours. Switch plant load to the backup compressor first.",
                      "Apply LOTO, then bleed the receiver tank to 0 psig before any work.",
                      "Inspect motor bearings for noise and heat. Replace the 6316 drive-end bearing if rough.",
                      "Send oil for analysis. Iron above 50 ppm confirms bearing or rotor wear.",
                      "After repair, run 4 hours and confirm vibration below 4.5 mm/s."],
             note="Running above 7.1 mm/s risks airend failure. A replacement airend has a 6 to 8 week lead time."),
        dict(code="T-05", name="High discharge temperature", severity="High",
             trigger="Discharge temperature above 220F. Controller shuts down at 230F.",
             causes=["Low oil level.", "Clogged oil cooler.", "Failed thermal valve.", "Room temperature above 104F."],
             actions=["Check oil level on the sight glass.", "Clean the oil cooler fins.", "Test the thermal valve.",
                      "Improve room ventilation."]),
        dict(code="P-07", name="Low oil pressure", severity="High",
             trigger="Oil injection pressure below 20 psig while loaded.",
             causes=["Clogged oil filter.", "Low oil level."],
             actions=["Replace the oil filter.", "Top up oil to the middle of the sight glass."]),
    ])
    s += [Paragraph("Preventive Maintenance", H2),
          table([["Task", "Interval"],
                 ["Vibration route reading", "Monthly; weekly if above 3.5 mm/s"],
                 ["Oil sample analysis", "Every 2,000 run hours"],
                 ["Replace oil filter and separator", "Every 4,000 run hours"],
                 ["Grease motor bearings", "Every 2,000 run hours, 30 g per bearing"]], [3.0, 3.5]),
          Paragraph(LOTO_NOTE + " Stored air pressure is a hazardous energy source. Bleed the receiver to 0 psig.", WARN)]
    return s

# --------------------------------------------------------------------------------------------
# Manual 4: CD-900 conveyor drive
# --------------------------------------------------------------------------------------------

def cd900():
    s = [
        Paragraph("1. Overview", H2),
        Paragraph("The Northgate CD-900 is a 10 HP (7.5 kW) gearmotor drive with variable frequency drive for belt and "
                  "roller conveyors up to 300 ft. The drive reports motor temperature, power draw and gearbox vibration.", BODY),
        Paragraph("2. Specifications", H2),
        table([["Item", "Value"],
               ["Motor", "7.5 kW, 460V / 3 ph, Class F insulation"],
               ["Full load amps (FLA)", "11.8 A"],
               ["Gearbox", "Helical-bevel, 20:1 ratio"],
               ["Belt speed", "60 to 240 ft/min"],
               ["Thermal protection", "PTC thermistor, trip at 155F frame temperature"]], [2.0, 4.5]),
        Paragraph("3. Normal Operating Ranges", H2),
        table([["Measurement", "Normal range", "Alarm limit"],
               ["Motor frame temperature", "100F to 135F", "Above 155F (TH-4)"],
               ["Power draw", "5.5 to 8.0 kW", "9.0 kW warning (OL-1), 10.5 kW for 30 s trip (OL-2)"],
               ["Gearbox vibration", "Below 3.5 mm/s", "Above 6.0 mm/s"]], [1.8, 1.9, 2.8]),
        PageBreak(),
    ]
    s += fault_section([
        dict(code="OL-1", name="Overload warning", severity="Low",
             trigger="Power draw above 9.0 kW for 60 seconds.",
             causes=["Heavy product mix during peak hours.", "Belt over-tensioned.", "Dragging rollers."],
             actions=["Check the load on the conveyor.", "Check belt tension (1% elongation target).",
                      "Spin rollers by hand under LOTO and replace any that drag."]),
        dict(code="OL-2", name="Overload trip", severity="High",
             trigger="Power draw above 10.5 kW for 30 seconds. VFD stops the motor.",
             causes=["Product jam at a merge or transfer (most common during afternoon peak).",
                     "Seized roller or bearing.", "Gearbox failure.", "Belt tracking off and rubbing the frame."],
             actions=["Apply LOTO before clearing any jam. Never reach into a stopped conveyor without LOTO.",
                      "Walk the full line and clear jams at merges and transfers.",
                      "Check for seized rollers and frame rub marks.",
                      "Let the motor cool below 135F before restart. Reset at the VFD keypad.",
                      "If OL-2 repeats 3 times in one shift, open a P2 work order and check the gearbox oil."],
             note="Repeated OL-2 trips also heat the motor. Check for TH-4 at the same time."),
        dict(code="JM-3", name="Jam detected", severity="Medium",
             trigger="Photo-eye blocked for more than 8 seconds while belt runs.",
             causes=["Product jam.", "Dirty photo-eye lens."],
             actions=["Apply LOTO and clear the jam.", "Clean the photo-eye lens."]),
        dict(code="TH-4", name="Motor thermal trip", severity="High",
             trigger="Motor frame temperature above 155F.",
             causes=["Repeated overloads.", "Blocked motor cooling fins.", "Low VFD output frequency for long periods."],
             actions=["Let the motor cool for at least 30 minutes.", "Clean the cooling fins.",
                      "Resolve any OL-1 or OL-2 cause before restart."]),
    ])
    s += [Paragraph("Preventive Maintenance", H2),
          table([["Task", "Interval"],
                 ["Check belt tension and tracking", "Weekly"],
                 ["Inspect rollers", "Monthly"],
                 ["Change gearbox oil", "Every 10,000 hours or 2 years"],
                 ["Clean motor fins", "Quarterly"]], [3.0, 3.5]),
          Paragraph(LOTO_NOTE, WARN)]
    return s

# --------------------------------------------------------------------------------------------
# Manual 5: BC-48 battery charger
# --------------------------------------------------------------------------------------------

def bc48():
    s = [
        Paragraph("1. Overview", H2),
        Paragraph("The Northgate BC-48 is a high-frequency charger for 48V lead-acid and lithium-ion forklift batteries. "
                  "It is networked over Ethernet and sends a heartbeat with temperature and power every 15 minutes. "
                  "Most charging happens overnight (10 PM to 6 AM) and during the midday break.", BODY),
        Paragraph("2. Specifications", H2),
        table([["Item", "Value"],
               ["Output", "48V DC, up to 250 A"],
               ["Input", "480V / 3 ph, 18 A"],
               ["Max output power", "14 kW"],
               ["Network", "Ethernet, heartbeat every 15 min"]], [2.0, 4.5]),
        Paragraph("3. Normal Operating Ranges", H2),
        table([["Measurement", "Normal range", "Alarm limit"],
               ["Cabinet temperature", "80F to 110F", "Above 130F (C-20)"],
               ["Power draw while charging", "10 to 14 kW", "-"],
               ["Power draw idle", "Below 1 kW", "-"],
               ["Heartbeat", "Every 15 min", "None for 15 min (C-01)"]], [1.8, 1.9, 2.8]),
        PageBreak(),
    ]
    s += fault_section([
        dict(code="C-01", name="Communication loss", severity="Medium",
             trigger="No heartbeat for 15 minutes. The charger logs C-01 when it reconnects.",
             causes=["Network switch or cable fault at the dock.", "Charger powered off at the disconnect.", "Controller board lockup."],
             actions=["Check that the charger display is on. If dark, check the disconnect and breaker.",
                      "Check the Ethernet link light. Reseat or replace the patch cable.",
                      "Power cycle the controller (disconnect off for 60 seconds).",
                      "Check whether any batteries missed their overnight charge and tell the shift lead."]),
        dict(code="C-12", name="Ground fault", severity="High",
             trigger="Leakage current above 30 mA.",
             causes=["Damaged output cable.", "Battery case contamination."],
             actions=["Tag the charger out of service.", "Inspect the output cable and connector.", "Clean the battery top."]),
        dict(code="C-20", name="Over-temperature", severity="Medium",
             trigger="Cabinet temperature above 130F.",
             causes=["Blocked air filter.", "Failed cooling fan.", "Charger installed in direct sun."],
             actions=["Clean the intake filter.", "Check the fan.", "Provide 12 in clearance on all sides."]),
        dict(code="C-33", name="Battery not accepting charge", severity="Low",
             trigger="Output current below 10 A for 20 minutes at the start of a cycle.",
             causes=["Sulfated or failed battery.", "Loose connector."],
             actions=["Check the connector.", "Send the battery for capacity testing."]),
    ])
    s += [Paragraph("Preventive Maintenance", H2),
          table([["Task", "Interval"],
                 ["Inspect output cable and connector", "Monthly"],
                 ["Clean intake filter", "Monthly"],
                 ["Check network connection", "Quarterly"]], [3.0, 3.5]),
          Paragraph(LOTO_NOTE, WARN)]
    return s

# --------------------------------------------------------------------------------------------
# SOPs
# --------------------------------------------------------------------------------------------

def sop001():
    return [
        Paragraph("1. Purpose and Scope", H2),
        Paragraph("This procedure protects employees from unexpected start-up or release of stored energy while servicing "
                  "refrigeration, compressed air, conveyor and battery charging equipment at all Northgate Distribution sites. "
                  "It follows the requirements of 29 CFR 1910.147.", BODY),
        Paragraph("2. Roles", H2),
        bullets(["<b>Authorized employee:</b> a maintenance technician trained on this SOP who applies locks and tags.",
                 "<b>Affected employee:</b> anyone who operates or works near the equipment. They must be told before and after LOTO.",
                 "<b>Maintenance supervisor:</b> keeps the lock log and audits this procedure once a year."]),
        Paragraph("3. General Lockout Steps", H2),
        steps(["Notify affected employees and the shift lead that the equipment will be shut down.",
               "Shut the equipment down with its normal stop control.",
               "Isolate every energy source listed in Section 4 for that equipment type.",
               "Apply your personal lock and a tag with your name, date and reason at each isolation point.",
               "Release or restrain stored energy (Section 4).",
               "Verify zero energy: try the start button, then test for voltage with a meter tested on a known live source.",
               "Perform the work.",
               "To remove LOTO: clear tools, replace guards, tell affected employees, remove your own lock only, then restart."]),
        Paragraph("4. Energy Sources by Equipment Type", H2),
        table([["Equipment", "Energy sources", "Stored energy step"],
               ["CU-400 condensing unit", "Electrical disconnect at unit; refrigerant under pressure", "Wait 5 minutes for fan capacitors to discharge. Do not open refrigerant lines unless certified under EPA Section 608."],
               ["EV-220 evaporator", "Electrical disconnect for fans and defrost heaters", "Wait 10 minutes for defrost heaters to cool. Heaters can exceed 400F."],
               ["AC-75 air compressor", "Electrical disconnect; compressed air in receiver and lines; hot oil", "Close the discharge isolation valve. Bleed the receiver tank to 0 psig and confirm on the gauge. Let oil cool below 120F."],
               ["CD-900 conveyor drive", "Electrical disconnect at VFD; gravity and belt tension", "Block or chock inclined sections. Release belt tension before removing pulleys."],
               ["BC-48 battery charger", "480V input disconnect; battery DC output", "Disconnect the battery connector from the charger before opening the cabinet."]],
              [1.5, 2.3, 2.7]),
        Paragraph("5. Group Lockout and Shift Change", H2),
        Paragraph("When more than one technician works on the same equipment, each person applies a personal lock to a "
                  "group lock box. At shift change the incoming technician applies a lock before the outgoing technician "
                  "removes theirs, so the equipment is never left without a lock.", BODY),
        Paragraph("6. Removing Another Person's Lock", H2),
        Paragraph("Only the maintenance supervisor may remove another person's lock, and only after trying to reach that "
                  "person by phone, confirming they have left the site, and recording the removal in the lock log. The "
                  "person must be told before they return to work.", BODY),
    ]


def sop002():
    return [
        Paragraph("1. Purpose", H2),
        Paragraph("This procedure defines what to do when a cooler or freezer goes outside its safe temperature range, "
                  "so that product safety decisions are consistent and documented.", BODY),
        Paragraph("2. Temperature Limits", H2),
        table([["Storage type", "Target", "Investigate when", "Product hold when"],
               ["Cooler (CU-400 units)", "34F to 38F", "Above 41F for 30 min", "Above 41F for more than 2 hours"],
               ["Freezer (EV-220 units)", "-15F to -5F", "Above 0F for 30 min", "Above 10F for more than 60 minutes"]],
              [1.6, 1.1, 1.8, 2.0]),
        Paragraph("3. Response Steps", H2),
        steps(["<b>Within 15 minutes:</b> the shift lead confirms the alarm by checking the unit display and a calibrated hand thermometer.",
               "<b>Within 15 minutes:</b> open a P1 work order under SOP-OPS-003 and call the on-call refrigeration technician.",
               "<b>Within 30 minutes:</b> if the unit cannot be restored, move product to a backup unit. Load the most temperature-sensitive product first (dairy, fresh meat, then produce; for freezers, ice cream first).",
               "Record start time, peak temperature, end time and product moved on form QA-17 Temperature Excursion Log.",
               "If a product hold limit in Section 2 was exceeded, tag affected pallets HOLD and notify Quality Assurance.",
               "<b>Within 24 hours:</b> QA decides product disposition: release, discount, or destroy."]),
        Paragraph("4. Root Cause", H2),
        Paragraph("The technician records the fault code and root cause in the work order. Common causes are door left open, "
                  "high head pressure (E-21), defrost termination failure (DF-4) and power loss. Any unit with two "
                  "excursions in 30 days gets a full inspection.", BODY),
        Paragraph("5. Records", H2),
        Paragraph("Keep QA-17 forms and temperature charts for 2 years.", BODY),
    ]


def sop003():
    return [
        Paragraph("1. Purpose", H2),
        Paragraph("This procedure sets response times for equipment alarms and explains how to open, update and close work "
                  "orders in the CMMS.", BODY),
        Paragraph("2. Priority Levels", H2),
        table([["Priority", "Definition", "Response time", "Who is notified"],
               ["P1", "Product at risk, safety hazard, or a line is down", "Technician on site within 30 minutes, 24/7", "On-call technician, shift lead, site maintenance manager"],
               ["P2", "Equipment degraded, failure likely within days", "Within 4 hours during staffed shifts", "On-call technician, shift lead"],
               ["P3", "Minor issue, no immediate impact", "Next business day", "Maintenance planner"]],
              [0.7, 2.0, 1.8, 2.0]),
        Paragraph("3. Fault Code to Priority Map", H2),
        table([["Fault code", "Equipment", "Priority"],
               ["E-21 with box temp above 38F, E-42", "CU-400", "P1"],
               ["E-21 with normal box temp, E-30", "CU-400", "P2"],
               ["DF-4, F-20", "EV-220", "P1"],
               ["F-11", "EV-220", "P2"],
               ["V-03, T-05, P-07", "AC-75", "P1"],
               ["V-02", "AC-75", "P2"],
               ["OL-2, TH-4", "CD-900", "P1 if the line is down, otherwise P2"],
               ["OL-1, JM-3", "CD-900", "P3"],
               ["C-12", "BC-48", "P1"],
               ["C-01, C-20", "BC-48", "P2"],
               ["E-14, F-31, C-33", "Various", "P3"]], [2.6, 1.4, 2.5]),
        Paragraph("4. Work Order Fields", H2),
        bullets(["Device ID (for example D-114) and site code.", "Fault code and time first seen.",
                 "Priority from Section 3.", "Actions taken, parts used, and readings before and after.",
                 "Root cause, chosen from the CMMS list."]),
        Paragraph("5. Escalation", H2),
        Paragraph("If a P1 is not acknowledged in 15 minutes, the monitoring system calls the backup technician. If not "
                  "resolved in 4 hours, the site maintenance manager notifies the regional engineering lead.", BODY),
        Paragraph("6. Site Codes", H2),
        table([["Code", "Site"], ["JOL", "Joliet, IL"], ["AUR", "Aurora, CO"], ["LAK", "Lakeland, FL"],
               ["STK", "Stockton, CA"], ["ALN", "Allentown, PA"]], [1.0, 3.0]),
    ]


def sop004():
    return [
        Paragraph("1. Purpose", H2),
        Paragraph("This procedure sets the preventive maintenance (PM) schedule for monitored equipment across all sites. "
                  "Intervals in the equipment manuals are minimums. Where this SOP is stricter, follow this SOP.", BODY),
        Paragraph("2. Site Adjustments", H2),
        Paragraph("Lakeland (LAK) and Stockton (STK) have high summer ambient temperatures and dust from nearby agriculture. "
                  "Condenser coils at these sites foul faster, so CU-400 coil cleaning is monthly there instead of quarterly. "
                  "Aurora (AUR) is at high altitude; AC-75 compressors there run hotter and get oil samples every 1,500 hours.", BODY),
        Paragraph("3. PM Schedule", H2),
        table([["Equipment", "Task", "Standard interval", "Site exceptions"],
               ["CU-400", "Clean condenser coil", "Quarterly", "Monthly at LAK and STK"],
               ["CU-400", "Check charge and subcooling", "Semi-annually", "-"],
               ["EV-220", "Test defrost termination sensor", "Quarterly", "-"],
               ["EV-220", "Check drain heater", "Quarterly", "Before Nov 1 at JOL, AUR and ALN"],
               ["AC-75", "Vibration route", "Monthly", "Weekly when above 3.5 mm/s"],
               ["AC-75", "Oil sample", "2,000 run hours", "1,500 hours at AUR"],
               ["CD-900", "Belt tension and tracking", "Weekly", "-"],
               ["CD-900", "Roller inspection", "Monthly", "-"],
               ["BC-48", "Cable and connector inspection", "Monthly", "-"]],
              [1.0, 2.2, 1.5, 1.8]),
        Paragraph("4. Condition-Based Triggers", H2),
        Paragraph("Monitoring data can trigger PM early:", BODY),
        bullets(["Any AC-75 with vibration rising more than 1.0 mm/s in 7 days gets an unscheduled vibration analysis.",
                 "Any CU-400 with head pressure averaging above 280 psig for 3 days gets a coil cleaning.",
                 "Any CD-900 with 3 or more OL-1 warnings in a week gets a roller and belt inspection."]),
        Paragraph("5. Records", H2),
        Paragraph("Close each PM work order in the CMMS with readings taken. Missed PMs are reported in the monthly "
                  "maintenance review.", BODY),
    ]


DOCS = [
    ("NG_CU-400_Condensing_Unit_Manual.pdf", "NG-MAN-CU400", "CU-400 Condensing Unit: Service Manual", cu400, {}),
    ("NG_EV-220_Freezer_Evaporator_Manual.pdf", "NG-MAN-EV220", "EV-220 Freezer Evaporator: Service Manual", ev220, {}),
    ("NG_AC-75_Air_Compressor_Manual.pdf", "NG-MAN-AC75", "AC-75 Rotary Screw Air Compressor: Service Manual", ac75, {}),
    ("NG_CD-900_Conveyor_Drive_Manual.pdf", "NG-MAN-CD900", "CD-900 Conveyor Drive: Service Manual", cd900, {}),
    ("NG_BC-48_Battery_Charger_Manual.pdf", "NG-MAN-BC48", "BC-48 Battery Charger: Service Manual", bc48, {}),
    ("SOP-OPS-001_Lockout_Tagout.pdf", "SOP-OPS-001", "Lockout/Tagout for Facility Equipment", sop001,
     dict(rev="4", date="2025-06-15", owner="Northgate Distribution, Facilities")),
    ("SOP-OPS-002_Cold_Chain_Excursion.pdf", "SOP-OPS-002", "Cold Chain Temperature Excursion Response", sop002,
     dict(rev="3", date="2025-01-10", owner="Northgate Distribution, Quality Assurance")),
    ("SOP-OPS-003_Alarm_Escalation.pdf", "SOP-OPS-003", "Equipment Alarm Escalation and Work Orders", sop003,
     dict(rev="2", date="2025-04-01", owner="Northgate Distribution, Facilities")),
    ("SOP-OPS-004_Preventive_Maintenance.pdf", "SOP-OPS-004", "Preventive Maintenance Program", sop004,
     dict(rev="5", date="2025-02-20", owner="Northgate Distribution, Facilities")),
]

if __name__ == "__main__":
    for fn, no, title, fn_story, kw in DOCS:
        p = build(fn, no, title, fn_story, **kw)
        print("wrote", p.relative_to(OUT.parents[1]))
