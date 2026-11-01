// The sources every figure and rule of 饮食与体重管理 (the diet mode, docs/diet.md) rests on: what each is, its version,
// what kind of support it gives (`label`), and what it does not support.  A result names the sources it used by id; the
// model is told to say which kind of support a recommendation has, never to present one kind as another.
//
// Labels:
//   modern_guideline           a current public-health or clinical guideline (its population and scope as stated)
//   food_composition           published food-composition data for a stated serving (HPB's analyses of Singapore
//                              dishes; USDA FoodData Central for plain foods)
//   local_data                 a published Singapore record: climate, public holidays, the lunar calendar
//   personalization_algorithm  this page's own transparent rule over the visitor's answers (not a trial result)
//   tcm_food_guideline         traditional food-property classification (寒热温凉; Singapore's "heaty"/"cooling"):
//                              cultural and dietary-preference guidance, not a diagnosis and not evidence of an effect
//   classical_text             what a classic says, quoted through the corpus tools and checked by the page: a historical
//                              statement, not modern evidence

export const ALGORITHM = "sg-diet-v1";

export const LABELS = {
  modern_guideline: "Current public-health or clinical guideline, within its stated population and scope.",
  food_composition: "Published food-composition data for the serving stated (HPB for Singapore dishes; USDA FoodData Central for plain foods).",
  local_data: "Published Singapore records (climate, public holidays, the lunar calendar).",
  personalization_algorithm: "This tool's own transparent rule applied to the user's answers; not a clinical-trial result.",
  tcm_food_guideline: "Traditional food-property classification (heaty/cooling, 寒热温凉): cultural dietary guidance, not a diagnosis or proof of effect.",
  classical_text: "What a classical text states (quoted and checked via the corpus): a historical statement, not modern clinical evidence.",
};

export const SOURCES = {
  sg_moh_cpg_obesity: {
    label: "modern_guideline", version: "2016",
    title: "Ministry of Health Singapore, Clinical Practice Guidelines: Obesity (with HPB)",
    supports: "BMI cut-offs for public-health action in Asian adults: 18.5–22.9 low risk, 23.0–27.4 moderate risk, ≥27.5 high risk; waist ≥90 cm (men) / ≥80 cm (women) raises risk.",
    not: "Diagnosis of an individual; BMI does not measure body composition.",
  },
  who_asian_bmi: {
    label: "modern_guideline", version: "2004",
    title: "WHO Expert Consultation. Appropriate body-mass index for Asian populations. Lancet 2004;363:157–63",
    supports: "Additional public-health action points for Asians at BMI 23, 27.5, 32.5 and 37.5.",
    not: "Individual risk without other measures.",
  },
  mifflin_st_jeor: {
    label: "modern_guideline", version: "1990",
    title: "Mifflin MD, St Jeor ST, et al. A new predictive equation for resting energy expenditure. Am J Clin Nutr 1990;51:241–7",
    supports: "Estimated resting energy expenditure of adults from weight, height, age and sex (individual error commonly ±10%).",
    not: "A measured requirement; children, pregnancy or illness.",
  },
  activity_factors: {
    label: "personalization_algorithm", version: ALGORITHM,
    title: "Physical-activity multipliers (sedentary 1.2–1.3, light 1.35–1.45, moderate 1.5–1.65, high 1.7–1.85)",
    supports: "A range for total energy expenditure as an assumption, to be revised by the weight trend over weeks.",
    not: "A measurement of the user's activity.",
  },
  hpb_healthy_plate: {
    label: "modern_guideline", version: "current (HealthHub)",
    title: "Health Promotion Board Singapore, My Healthy Plate (quarter wholegrains, quarter protein, half fruit and vegetables; 10-inch plate; choose water; healthier oils)",
    supports: "Plate proportions and food-group choices for healthy adults in Singapore.",
    not: "Individual medical nutrition therapy.",
  },
  hpb_sodium: {
    label: "modern_guideline", version: "current; intake figures from the National Nutrition Survey 2025 as reported in 2026",
    title: "HPB: sodium no more than 2,000 mg a day (about one teaspoon of salt, 5 g)",
    supports: "The daily sodium limit for adults; Singapore residents' average intake was about double it in 2025.",
    not: "Targets for kidney or heart disease set by a clinician.",
  },
  hpb_sugar: {
    label: "modern_guideline", version: "current",
    title: "HPB: added sugar no more than 10% of daily energy (about 50 g, 10 teaspoons, on 2,000 kcal)",
    supports: "The daily added-sugar limit, scaled to an energy intake.",
    not: "Carbohydrate targets for diabetes.",
  },
  hpb_nutri_grade: {
    label: "modern_guideline", version: "Food Regulations (Nutri-Grade), in force from 30 Dec 2022",
    title: "Nutri-Grade for beverages: A ≤1 g sugar & ≤0.7 g sat fat /100 ml; B ≤5 g & ≤1.2 g; C ≤10 g & ≤2.8 g; D above",
    supports: "Choosing pre-packed and freshly prepared drinks by their grade (the lower of the sugar and saturated-fat grades).",
    not: "The healthiness of food other than beverages.",
  },
  who_healthy_diet: {
    label: "modern_guideline", version: "fact sheet, current",
    title: "World Health Organization, Healthy diet (≥400 g fruit and vegetables a day; free sugars <10% of energy; salt <5 g; saturated fat <10%)",
    supports: "Population dietary goals for adults.",
    not: "Individual prescriptions.",
  },
  who_carbohydrate: {
    label: "modern_guideline", version: "2023",
    title: "WHO guideline: carbohydrate intake for adults and children (at least 25 g of naturally occurring dietary fibre a day for adults)",
    supports: "The fibre reference for adults; wholegrains, vegetables, fruit and pulses as its sources.",
    not: "Fibre targets in bowel disease.",
  },
  protein_reference: {
    label: "personalization_algorithm", version: ALGORITHM,
    title: "Protein about 1.0–1.2 g per kg of reference weight during weight loss or after 65 (0.8 g/kg the adult minimum); reference weight = the weight at BMI 25 when BMI ≥ 27.5",
    supports: "A protein range to keep meals filling and muscle preserved, alongside resistance exercise.",
    not: "Kidney disease, where protein is set by the renal team.",
  },
  hpb_dish_composition: {
    label: "food_composition", version: "values as published by HPB (Energy & Nutrient Composition of Food); retrieved through secondary sources quoting HPB codes — verify against focos.hpb.gov.sg before production",
    title: "Health Promotion Board Singapore, Energy & Nutrient Composition of Food",
    supports: "Energy and nutrients of a typical serving of a Singapore dish as HPB analysed it.",
    not: "The exact portion a given stall serves: real servings vary.",
  },
  usda_fdc: {
    label: "food_composition", version: "SR Legacy entries named on each item, per 100 g scaled to the serving shown",
    title: "U.S. Department of Agriculture, FoodData Central (plain foods: brown rice, tofu, egg, pak choi, banana, apple, watermelon)",
    supports: "Energy and macronutrients of plain foods for the serving shown (without added oil, salt or sauce).",
    not: "A dish's sauce, oil or salt, which the serving does not include.",
  },
  mss_climate: {
    label: "local_data", version: "climatology (typical onsets; vary year to year)",
    title: "Meteorological Service Singapore: Northeast Monsoon (Dec–early Mar), inter-monsoon (late Mar–May), Southwest Monsoon (Jun–Sep), inter-monsoon (Oct–Nov)",
    supports: "The typical season and its weather for a date in Singapore, without live observations.",
    not: "Today's actual weather, rain or haze: check NEA/MSS for those.",
  },
  mom_holidays: {
    label: "local_data", version: "MOM public holidays 2026 (announced 2025) and 2027 (announced 18 June 2026), as reported",
    title: "Ministry of Manpower Singapore, public holidays",
    supports: "Dates of the festive seasons the plan prepares for.",
    not: "Religious observance dates set by moon sighting (MUIS announces Ramadan and Hari Raya).",
  },
  lunar_calendar: {
    label: "local_data", version: "published calendars (2026-09-25, 2027-09-15)",
    title: "Mid-Autumn Festival: the 15th day of the 8th lunar month",
    supports: "The date of the Mid-Autumn Festival in Singapore.",
    not: "Anything about the season's weather.",
  },
  solar_terms: {
    label: "personalization_algorithm", version: "Meeus, Astronomical Algorithms (2nd ed., 1998), ch. 25; checked against the National Astronomical Observatory of Japan's 2026 almanac",
    title: "The 24 solar terms (二十四节气) from the Sun's apparent longitude, in Singapore time (UTC+8, the same as China Standard Time)",
    supports: "The cultural calendar date (e.g. 冬至 Dongzhi) in Singapore.",
    not: "Singapore's climate, which the monsoons govern, not the northern-temperate seasons the terms describe.",
  },
  tcm_food_nature: {
    label: "tcm_food_guideline", version: ALGORITHM,
    title: "Traditional food natures (寒/凉/平/温/热) and Singapore's everyday 'heaty' (热气) / 'cooling' (凉) food culture; only foods where common references agree",
    supports: "Food choices that suit a stated preference (warm cooked food, lighter food) within the nutrition plan.",
    not: "A TCM pattern or constitution diagnosis (须由注册中医师诊察), a treatment, or evidence of weight loss.",
  },
};

/** The sources named by `ids`, as a result carries them: id, label, title, version. */
export function provenance(ids) {
  return [...new Set(ids)].filter((id) => SOURCES[id]).map((id) => ({ id, label: SOURCES[id].label, title: SOURCES[id].title, version: SOURCES[id].version }));
}
