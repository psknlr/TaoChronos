// The sources every figure and rule of 饮食与体重管理 (the diet mode, docs/diet.md) rests on: what each is, its version,
// what kind of support it gives (`label`), and what it does not support.  A result names the sources it used by id; the
// model is told to say which kind of support a recommendation has, never to present one kind as another.
//
// Labels:
//   modern_guideline           a current public-health or clinical guideline (its population and scope as stated)
//   food_composition           published food-composition data for a stated serving (USDA FoodData Central for plain
//                              foods; HPB's analyses of Singapore dishes)
//   local_data                 a published calendar or climate record: holidays, the lunar calendar, a climatology
//   personalization_algorithm  this page's own transparent rule over the visitor's answers (not a trial result)
//   tcm_food_guideline         traditional food-property classification (寒热温凉; the everyday "heaty"/"cooling"):
//                              cultural and dietary-preference guidance, not a diagnosis and not evidence of an effect
//   classical_text             what a classic says, quoted through the corpus tools and checked by the page: a historical
//                              statement, not modern evidence

export const ALGORITHM = "diet-v2";

export const LABELS = {
  modern_guideline: "Current public-health or clinical guideline, within its stated population and scope.",
  food_composition: "Published food-composition data for the serving stated (USDA FoodData Central for plain foods; HPB for Singapore dishes).",
  local_data: "Published calendars and climate records (holidays, the lunar calendar, a climatology).",
  personalization_algorithm: "This tool's own transparent rule applied to the user's answers; not a clinical-trial result.",
  tcm_food_guideline: "Traditional food-property classification (heaty/cooling, 寒热温凉): cultural dietary guidance, not a diagnosis or proof of effect.",
  classical_text: "What a classical text states (quoted and checked via the corpus): a historical statement, not modern clinical evidence.",
};

const G = (version, title, supports, not) => ({ label: "modern_guideline", version, title, supports, not });

export const SOURCES = {
  // ------------------------------------------------------------------ body weight
  who_bmi: G("WHO, Obesity: preventing and managing the global epidemic (TRS 894, 2000)",
    "WHO international BMI classification for adults (18.5 / 25 / 30; obesity classes at 35 and 40)",
    "The default BMI scale for adults where no other applies.", "Diagnosis of an individual; BMI does not measure body composition."),
  lower_bmi: G("WHO Expert Consultation, Lancet 2004;363:157–63; NICE CG189 (2022) and NG246",
    "Lower BMI thresholds for Asian populations (WHO 2004: action points 23, 27.5, 32.5, 37.5) and, in NICE's guidance, for South Asian, Chinese, other Asian, Middle Eastern, Black African and African-Caribbean family backgrounds (overweight 23–27.4, obesity ≥27.5); the same cut-offs in Singapore's MOH Clinical Practice Guidelines on Obesity (2016)",
    "Reading BMI for people whose cardiometabolic risk rises at a lower BMI.", "Individual risk without other measures."),
  china_bmi: G("WS/T 428-2013 (National Health Commission of China)",
    "China's adult weight standard: BMI 18.5–23.9 normal, 24–27.9 overweight, ≥28 obesity; central obesity at a waist of ≥90 cm (men) / ≥85 cm (women), pre-central from 85 / 80 cm",
    "Reading BMI and waist for adults in China.", "Children, pregnancy or older adults."),
  who_waist: G("WHO TRS 894 (2000); the 2008 WHO expert consultation on waist circumference",
    "Waist circumference: risk increased at ≥94 cm (men) / ≥80 cm (women) and substantially increased at ≥102 / ≥88 cm; for Asian populations ≥90 / ≥80 cm",
    "A measure of central fat alongside BMI.", "Diagnosis."),
  // ------------------------------------------------------------------ energy and protein
  mifflin_st_jeor: G("1990",
    "Mifflin MD, St Jeor ST, et al. A new predictive equation for resting energy expenditure. Am J Clin Nutr 1990;51:241–7",
    "Estimated resting energy expenditure of adults from weight, height, age and sex (individual error commonly ±10%).",
    "A measured requirement; children, pregnancy or illness."),
  activity_factors: {
    label: "personalization_algorithm", version: ALGORITHM,
    title: "Physical-activity multipliers (sedentary 1.2–1.3, light 1.35–1.45, moderate 1.5–1.65, high 1.7–1.85)",
    supports: "A range for total energy expenditure as an assumption, to be revised by the weight trend over weeks.",
    not: "A measurement of the user's activity.",
  },
  protein_reference: {
    label: "personalization_algorithm", version: ALGORITHM,
    title: "Protein about 1.0–1.2 g per kg of reference weight during weight loss or after 65 (0.8 g/kg the adult minimum); reference weight = the weight at BMI 25 when BMI is in the obesity range",
    supports: "A protein range to keep meals filling and muscle preserved, alongside resistance exercise.",
    not: "Kidney disease, where protein is set by the renal team.",
  },
  // ------------------------------------------------------------------ food guides
  who_healthy_diet: G("fact sheet, current",
    "World Health Organization, Healthy diet (≥400 g fruit and vegetables a day; free sugars <10% of energy, ideally <5%; salt <5 g; saturated fat <10%)",
    "Population dietary goals for adults, worldwide.", "Individual prescriptions."),
  who_carbohydrate: G("2023",
    "WHO guideline: carbohydrate intake for adults and children (at least 25 g of naturally occurring dietary fibre a day for adults)",
    "The fibre reference for adults; wholegrains, vegetables, fruit and pulses as its sources.", "Fibre targets in bowel disease."),
  us_dga: G("Dietary Guidelines for Americans 2025–2030 (January 2026); sodium limit of 2,300 mg from the 2020–2025 edition",
    "USDA/HHS, Dietary Guidelines for Americans and MyPlate (saturated fat <10% of calories; added sugars limited; sodium under 2,300 mg)",
    "Food-group and limit guidance for adults in the United States.", "Individual medical nutrition therapy."),
  uk_eatwell: G("Eatwell Guide (2016); NHS salt and sugar advice",
    "Public Health England / NHS, Eatwell Guide; adults no more than 6 g salt and 30 g free sugars a day",
    "Food-group and limit guidance for adults in the UK.", "Individual medical nutrition therapy."),
  cn_guidelines: G("Dietary Guidelines for Chinese Residents (2022)",
    "Chinese Nutrition Society, 中国居民膳食指南（2022）and the Chinese Food Guide Plate (salt <5 g and cooking oil 25–30 g a day)",
    "Food-group and limit guidance for adults in China.", "Individual medical nutrition therapy."),
  ca_food_guide: G("2019", "Health Canada, Canada's Food Guide (half vegetables and fruits, a quarter whole grain foods, a quarter protein foods; water)",
    "Plate proportions for adults in Canada.", "Individual medical nutrition therapy."),
  au_guide: G("Australian Dietary Guidelines (NHMRC, 2013)", "NHMRC, Australian Guide to Healthy Eating (five food groups)",
    "Food-group guidance for adults in Australia.", "Individual medical nutrition therapy."),
  jp_guide: G("2005 (MHLW, MAFF)", "Japanese Food Guide Spinning Top (食事バランスガイド)",
    "Food-group guidance for adults in Japan.", "Individual medical nutrition therapy."),
  in_guidelines: G("2024 (verify the current text)", "ICMR–National Institute of Nutrition, Dietary Guidelines for Indians: 'My Plate for the Day'",
    "Food-group guidance for adults in India.", "Individual medical nutrition therapy."),
  my_healthy_plate: G("current (verify the current text)", "Ministry of Health Malaysia, Malaysian Healthy Plate ('Suku-Suku Separuh')",
    "Plate proportions for adults in Malaysia.", "Individual medical nutrition therapy."),
  hpb_healthy_plate: G("current (HealthHub)",
    "Health Promotion Board Singapore, My Healthy Plate (quarter wholegrains, quarter protein, half fruit and vegetables; water; healthier oils)",
    "Plate proportions and food-group choices for adults in Singapore.", "Individual medical nutrition therapy."),
  hpb_sodium: G("current; intake from the National Nutrition Survey 2025 as reported in 2026",
    "HPB: sodium no more than 2,000 mg a day (about one teaspoon of salt, 5 g)",
    "The daily sodium limit for adults in Singapore.", "Targets for kidney or heart disease set by a clinician."),
  hpb_sugar: G("current", "HPB: added sugar no more than 10% of daily energy",
    "The daily added-sugar limit in Singapore, scaled to an energy intake.", "Carbohydrate targets for diabetes."),
  hpb_nutri_grade: G("Food Regulations (Nutri-Grade), in force from 30 Dec 2022",
    "Singapore's Nutri-Grade for beverages: A ≤1 g sugar & ≤0.7 g sat fat /100 ml; B ≤5 g & ≤1.2 g; C ≤10 g & ≤2.8 g; D above",
    "Choosing drinks sold in Singapore by their grade.", "The healthiness of food other than beverages."),
  food_safety: G("WHO Five Keys to Safer Food (2006); USDA food-safety advice",
    "Do not leave cooked food at room temperature for more than 2 hours (1 hour above 32 °C / 90 °F); refrigerate promptly",
    "Food safety in warm weather.", "Medical advice."),
  // ------------------------------------------------------------------ food composition
  usda_fdc: {
    label: "food_composition", version: "SR Legacy entries named on each item, per 100 g scaled to the serving shown",
    title: "U.S. Department of Agriculture, FoodData Central (plain foods and the meals built from them)",
    supports: "Energy and nutrients of plain foods for the serving shown; a meal's values are the sum of its parts.",
    not: "Salt, sauce or oil the recipe does not list; a local dish of the same name.",
  },
  hpb_dish_composition: {
    label: "food_composition", version: "values as published by HPB (Energy & Nutrient Composition of Food); retrieved through secondary sources quoting HPB — verify against focos.hpb.gov.sg before production",
    title: "Health Promotion Board Singapore, Energy & Nutrient Composition of Food",
    supports: "Energy and nutrients of a typical serving of a Singapore dish as HPB analysed it.",
    not: "The exact portion a given stall serves: real servings vary.",
  },
  // ------------------------------------------------------------------ calendars and climate
  climate_rule: {
    label: "personalization_algorithm", version: ALGORITHM,
    title: "Seasons from the hemisphere and the country's broad climate (temperate, cold, subtropical, arid, tropical, monsoon)",
    supports: "Seasonal food, hydration and food-safety advice for a date and a country.",
    not: "Today's weather or a particular city's climate: large countries span several climates.",
  },
  mss_climate: {
    label: "local_data", version: "climatology (typical onsets; vary year to year)",
    title: "Meteorological Service Singapore: Northeast Monsoon (Dec–early Mar), inter-monsoon (late Mar–May), Southwest Monsoon (Jun–Sep), inter-monsoon (Oct–Nov)",
    supports: "The typical season for a date in Singapore, without live observations.",
    not: "Today's actual weather, rain or haze.",
  },
  festival_calendar: {
    label: "local_data", version: "computed (Christmas, Western Easter, Thanksgiving) and published calendars for 2026–2027",
    title: "Festive dates: computed where a rule fixes them; lunar, Islamic and Hindu dates from published calendars (Islamic and Hindu ones approximate: they follow moon sighting and local calendars)",
    supports: "Which festive seasons are coming, to plan festive eating.",
    not: "The exact local date of a festival set by a local authority's announcement.",
  },
  solar_terms: {
    label: "personalization_algorithm", version: "Meeus, Astronomical Algorithms (2nd ed., 1998), ch. 25; checked against the National Astronomical Observatory of Japan's 2026 almanac",
    title: "The 24 solar terms (二十四节气) from the Sun's apparent longitude, dated in China Standard Time (UTC+8)",
    supports: "The Chinese cultural calendar (e.g. 冬至 Dongzhi).",
    not: "The climate outside the northern temperate zone the terms describe.",
  },
  tcm_food_nature: {
    label: "tcm_food_guideline", version: ALGORITHM,
    title: "Traditional food natures (寒/凉/平/温/热) and the everyday 'heaty' (热气) / 'cooling' (凉) food culture; only foods where common references agree",
    supports: "Food choices that suit a stated preference (warm cooked food, lighter food) within the nutrition plan.",
    not: "A TCM pattern or constitution diagnosis (须由注册中医师诊察), a treatment, or evidence of weight loss.",
  },
};

/** The sources named by `ids`, as a result carries them: id, label, title, version. */
export function provenance(ids) {
  return [...new Set(ids)].filter((id) => SOURCES[id]).map((id) => ({ id, label: SOURCES[id].label, title: SOURCES[id].title, version: SOURCES[id].version }));
}
