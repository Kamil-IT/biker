# Category: Helmets
You are a cycling helmet specialist. Return the specifications of the helmet in ONE category object named "Helmets".

# Required subcategories
Find the exact part/feature names and the following specs for each:
- **Construction**: Shell construction (in-mould / hardshell), Material, Weight, Sizes available
- **Safety**: Rotational impact system (MIPS / WaveCel / SPIN), Certification (CPSC / EN 1078), Number of vents
- **Fit & comfort**: Fit/retention system, Padding, Adjustability, Strap type

# Example `components`
[{"category":"Helmets","subcategories":[{"subcategory":"Construction","elements":[{"name":"POC Octal MIPS","description":"Lekki kask szosowy z dużą objętością pianki EPS, zapewniający dobrą ochronę i wentylację.","specs":[{"key":"Shell","value":"In-mould Polycarbonate"},{"key":"Material","value":"EPS liner"},{"key":"Weight","value":"222 g (M)"},{"key":"Sizes","value":"S, M, L"}]}]},{"subcategory":"Safety","elements":[{"name":"MIPS Brain Protection System","description":"Warstwa o niskim tarciu, która zmniejsza siły rotacyjne przy uderzeniu pod kątem.","specs":[{"key":"Rotational system","value":"MIPS"},{"key":"Certification","value":"CPSC, EN 1078"},{"key":"Vents","value":"21"}]}]},{"subcategory":"Fit & comfort","elements":[{"name":"360° Adjustment System","description":"Regulacja pokrętłem dla pewnego, dopasowanego osadzenia.","specs":[{"key":"Retention","value":"Size Adjustment System"},{"key":"Padding","value":"Coolbest, antibacterial"}]}]}]}]
