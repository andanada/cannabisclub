# Revisión legal preliminar (protección de datos y marco del club)

> **Qué es y qué no es.** Análisis hecho por una IA a partir de fuentes públicas (18/11/2026). **No es asesoramiento jurídico** ni sustituye a un abogado
> colegiado ni a un DPO. Sirve para llegar a la reunión con el abogado con los problemas ya localizados. Las fuentes secundarias (blogs, prensa, doctrina)
> deben contrastarse con el texto oficial (BOE, CENDOJ, web del Tribunal Constitucional y de la AEPD).

## 1. El riesgo principal no es el RGPD: es el estatus del propio club

Las fuentes consultadas coinciden en lo esencial:

- El Tribunal Supremo (STS 484/2015, caso EBERS, Pleno de la Sala Segunda, 7/9/2015) rechazó extender la doctrina del «consumo compartido» a las
  asociaciones cannábicas por el riesgo de difusión y la imposibilidad de controlarlo. ([análisis académico](https://core.ac.uk/download/51283926.pdf), [TNI](https://www.tni.org/es/art%C3%ADculo/las-nuevas-sentencias-del-tribunal-constitucional-el-final-de-la-tolerancia-hacia-el))
- El Tribunal Constitucional anuló las leyes autonómicas que regulaban estos clubes: la de Navarra (2014) y la de Cataluña (2017, [STC 100/2018, BOE-A-2018-13998](https://hj.tribunalconstitucional.es/HJ/docs/BOE/BOE-A-2018-13998.pdf)). La competencia es estatal y los ayuntamientos tampoco
  pueden regularlos ([Redacción Médica](https://www.redaccionmedica.com/secciones/derecho/la-competencia-sobre-clubs-de-cannabis-es-del-estado-y-no-de-los-municipios-6354)).
- Consecuencia práctica: **un fichero con quién consume cuánto, dónde y cuándo es material sensible en cualquier investigación**. Esto afecta al diseño
  de datos (minimización, retención corta, quién puede acceder) más que a cualquier texto informativo.

**Acción:** abogado penalista con experiencia en asociaciones cannábicas, antes de abrir. Es la decisión con más consecuencias de todo el proyecto y queda
fuera de lo que el software puede resolver.

## 2. Texto informativo v1 (`backend/app/textos/v1/ca.txt`): carencias detectadas

El texto actual es un esqueleto correcto en forma, pero incompleto para el art. 13 RGPD:

| # | Carencia | Gravedad | Qué hacer |
|---|---|---|---|
| 1 | El responsable es «el que indique el local»: no hay denominación, NIF, domicilio ni correo de contacto reales. | Alta | Rellenar con los datos de la asociación (se puede parametrizar por local). |
| 2 | Base jurídica del tratamiento básico: «ejecución de la relación asociativa y cumplimiento de obligaciones legales». **No se identifica ninguna obligación legal concreta**; citarla sin base es un defecto. | Alta | Quitar «obligaciones legales» o citar la norma exacta (p. ej. contable/fiscal, si aplica). |
| 3 | El «registro de actividad» incluye los **gramos dispensados por socio**, que revela consumo de cannabis. Puede considerarse dato de categoría especial (salud, art. 9 RGPD) o, como mínimo, de riesgo alto. La ejecución de un contrato **no** levanta la prohibición del art. 9.1; haría falta una excepción del art. 9.2, normalmente consentimiento **explícito** (9.2.a). La AEPD interpreta «dato de salud» de forma amplia ([ejemplo en un caso de farmacia](https://www.fieldfisher.com/es-es/locations/espana/actualidad/propietario-de-una-farmacia-asi-debe-tratar-los-datos-personales)). | Alta | Decidirlo con el abogado/DPO. Opción prudente: consentimiento explícito, separado y revocable para el registro de consumo, y documentar el razonamiento si se concluye que no es categoría especial. |
| 4 | Faltan: plazos concretos de conservación, derecho a retirar el consentimiento *en cada finalidad* (consta en foto y contacto, no en el básico), si dar los datos es obligatorio y consecuencias de no darlos, ausencia de decisiones automatizadas, y derecho de limitación indicado pero sin procedimiento. | Media | Completar en v2. |
| 5 | «No se ceden datos a terceros excepto obligación legal»: declarar también los **encargados** (alojamiento, copias remotas) y si hay transferencias fuera del EEE. | Media | Listar encargados y ubicación; firmar contrato del art. 28. |
| 6 | El texto está en catalán/castellano/inglés, pero no hay versión en lenguaje claro para firmar en tableta (la información debe ser «concisa, transparente, inteligible»). | Baja | Revisar redacción con el abogado. |

Para la v2 hay que **crear una versión nueva** (`textos/v2/`), nunca editar la v1 publicada: el sistema guarda el hash de lo que cada socio firmó.

## 3. Obligaciones que el programa no puede cumplir solo

1. **Registro de actividades de tratamiento (art. 30)**: plantilla en `docs/RGPD.md` §A; rellenarla.
2. **EIPD (art. 35)**: muy probablemente necesaria si el registro de consumo es dato de categoría especial o el tratamiento es sistemático; la checklist está en
   `docs/RGPD.md` §B. La obligatoriedad cuando se tratan datos del art. 9 «a gran escala» consta en el art. 35.3.b RGPD; para un club pequeño la escala es
   discutible, pero la AEPD insiste en el análisis de riesgos documentado (la falta de análisis de riesgos aparece como agravante en sus resoluciones).
3. **DPO**: no he encontrado base para afirmar que sea obligatorio en un club pequeño; confirmar con el art. 37 RGPD y el art. 34 LOPDGDD.
4. **Contratos del art. 28** con quien aloje el servidor y las copias.
5. **Procedimiento de brecha (72 h)**: descrito en `docs/PRODUCCIO.md` §6; practicarlo una vez.
6. **Plazos de conservación**: `CLUB_RETENCIO_MIN_DIES=365` es un valor técnico prudente, **no** una obligación legal. Fijarlo con las obligaciones fiscales y contables
   reales (cifras habituales: 4 años tributarios, 6 años contables; **verificar**).
7. **Estatutos y registro de la asociación**: el modelo de aval, período de espera y límites por socio deben estar amparados por los estatutos.

## 4. Decisiones de diseño que reducen el riesgo (y que puedo implementar si se aprueban)

- **Minimizar el historial de consumo**: conservar el detalle por socio solo el tiempo necesario para los límites (día/mes) y agregar después. Hoy se conserva
  todo en tablas de solo añadir (la supresión se hace por seudonimización).
- **Consentimiento explícito de consumo** como finalidad propia (`consents`, finalidad nueva), con retirada que impida dispensar.
- **Firma en tableta**: guardar solo la imagen (ya se hace) y no los datos dinámicos de trazo/presión, que serían biométricos (art. 9).
- **Copias**: política de rotación coherente con el derecho de supresión (las copias anteriores a una supresión conservan los datos).
- **Acceso**: ya restringido por rol (el censo nominal solo para responsables) y auditado.

## 5. Lo que el programa ya cubre (técnico)

Cifrado de campos y copias, auditoría encadenada con HMAC, mínimo privilegio en BD, consentimientos versionados con hash, exportación/portabilidad,
supresión por seudonimización, retención automática, informes con umbral k=5 y registro de accesos. Detalle en `docs/RGPD.md` §C.

## 6. Qué llevar al abogado

1. ¿Es legalmente viable el club en su comunidad y bajo qué fórmula estatutaria? (punto 1)
2. ¿Es categoría especial el registro de consumo? ¿Qué base jurídica? (punto 2.3)
3. Texto v2 definitivo, con responsable real, bases, plazos y encargados.
4. Plazos de conservación y qué hacer ante un requerimiento de una autoridad.
5. ¿Hace falta EIPD y DPO?
