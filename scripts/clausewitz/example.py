from clausewitz import ClausewitzDocument, DocumentSchema, KeyRule
from clausewitz.query import replace_values, scale_numeric_values

example_text_1 = """
building_company_headquarter = { # hello world
	aliases = { } building_group = bg_company_headquarter
	city_type = city
	levels_per_mesh = 50

	lens = infrastructure

	icon = "gfx/interface/icons/building_icons/building_company_hq.dds"

	production_method_groups = {
		pmg_ownership_building_company_headquarter
        pmg_ownership_building_company_headquarter_1
        pmg_ownership_building_company_headquarter_3
        pmg_ownership_building_company_headquarter_4
	}

	investment_scores = {}

	buildable = no
	expandable = no
	downsizeable = no
	ownership_type = other

	background = "gfx/interface/icons/building_icons/backgrounds/building_panel_bg_monuments.dds"
}

building_company_regional_headquarter = {
	aliases = { } building_group = bg_company_regional_headquarter
	city_type = city
	levels_per_mesh = 50

	lens = infrastructure

	icon = "gfx/interface/icons/building_icons/building_company_regional_hq.dds"

	production_method_groups = {
		pmg_ownership_building_company_headquarter
	}

	investment_scores = {}

	buildable = no
	expandable = no
	downsizeable = no
	ownership_type = other

	background = "gfx/interface/icons/building_icons/backgrounds/building_panel_bg_monuments.dds"
}
"""

example_text_2 = """
pm_automation_0_building_agriculture = {
	texture = "gfx/interface/icons/production_method_icons/no_automation.dds"
	
}

pm_automation_1_building_agriculture = {
	texture = "gfx/interface/icons/production_method_icons/harvesting_tools.dds"

	unlocking_technologies = {
		tech_agriculture_1
	}
	
	state_modifiers = { workforce_scaled = { state_pollution_generation_add = 1 } }

	building_modifiers = {
	
		#More electricity required
		workforce_scaled = {
			goods_input_industrial_robots_add = 0.5
			#goods_input_electricity_add = 1
			goods_input_oil_add = 0.5
			#goods_input_transportation_add = 0.5
			goods_input_intellectual_property_add = 0.25
			
			goods_input_industrial_chemicals_add = 0.5
			
			#goods_input_communication_services_add = 0.5
			
			#goods_input_professional_services_add = 0.5
		}
	
		#Less employees required
		level_scaled = {
			building_employment_farmers_add = -1000
		}
		
	}
	
}

pm_automation_2_building_agriculture = {
	texture = "gfx/interface/icons/production_method_icons/tractors.dds"

	unlocking_technologies = {
		tech_agriculture_2
	}
	
	state_modifiers = { workforce_scaled = { state_pollution_generation_add = 2 } }

	building_modifiers = {
	
		#More electricity required
		workforce_scaled = {
			goods_input_industrial_robots_add = 1
			#goods_input_electricity_add = 2
			goods_input_oil_add = 1
			#goods_input_transportation_add = 1.0
			goods_input_intellectual_property_add = 0.5
			
			goods_input_industrial_chemicals_add = 1
			
			#goods_input_communication_services_add = 1
			
			#goods_input_professional_services_add = 1.0
		}
	
		#Less employees required
		level_scaled = {
			building_employment_farmers_add = -2000
		}
		
	}
	
}
"""


def example_1() -> None:
    text = example_text_1
    schema = DocumentSchema(name="example", root_key="root", root_rule=KeyRule(name="root", repeatable=False))
    doc = ClausewitzDocument.from_text(text, schema=schema)

    replace_values(
        doc.root,
        key_pattern="expandable",
        new_raw="yes",
        ancestor_suffix_pattern="**.building_*",
        operator="=",
        session=doc.session,
    )
    replace_values(
        doc.root,
        key_pattern="lens",
        new_raw="my_new_lens",
        ancestor_suffix_pattern="**.building_*",
        operator="=",
        session=doc.session,
    )
    scale_numeric_values(
        doc.root,
        key_pattern="levels_per_mesh",
        factor=2.0,
        ancestor_suffix_pattern="**.building_*",
        operator="=",
        session=doc.session,
    )
    new_text = doc.apply()
    print(new_text)
    doc.save("example_1_output.txt", mode="preserve")
    doc.save("example_1_canonical.txt", mode="canonical")


def example_2() -> None:
    pass
