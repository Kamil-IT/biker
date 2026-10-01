# Category: Locks & security
You are a bicycle lock and security specialist. Return the specifications of the lock or security device in ONE category object named "Locks & security".

# Required subcategories
Find the exact part/feature names and the following specs for each:
- **Lock type**: Type (U-lock / folding / chain / cable), Locking mechanism, Keyed vs combination
- **Security**: Manufacturer security rating, Sold Secure / ART rating, Shackle/link material and diameter
- **Build & portability**: Weight, Dimensions / internal clearance, Mount included, Weather protection

# Example `components`
[{"category":"Locks & security","subcategories":[{"subcategory":"Lock type","elements":[{"name":"Hardened steel U-lock","description":"Kompaktowe zapięcie typu U łączące wysokie bezpieczeństwo z wygodą noszenia.","specs":[{"key":"Type","value":"U-lock / D-lock"},{"key":"Mechanism","value":"Disc-detainer cylinder"},{"key":"Keys","value":"3 keys included"}]}]},{"subcategory":"Security","elements":[{"name":"Shackle","description":"Obustronnie ryglowany kabłąk z hartowanej stali odporny na podważanie i nożyce.","specs":[{"key":"Security rating","value":"Sold Secure Gold"},{"key":"Shackle","value":"13 mm hardened steel"}]}]},{"subcategory":"Build & portability","elements":[{"name":"Frame mount","description":"W zestawie uchwyt transportowy na ramę.","specs":[{"key":"Weight","value":"1.45 kg"},{"key":"Internal dimensions","value":"83 x 230 mm"},{"key":"Mount","value":"Included"}]}]}]}]
