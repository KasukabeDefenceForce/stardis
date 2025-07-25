from pathlib import Path
import logging
import numpy as np

from tardis.io.atom_data import AtomData
from tardis.io.configuration.config_validator import validate_yaml, validate_dict
from tardis.io.configuration.config_reader import Configuration

from stardis.io.model.marcs import read_marcs_model
from stardis.io.model.mesa import read_mesa_model
from stardis.io.model.util import rescale_nuclide_mass_fractions


BASE_DIR = Path(__file__).parent
SCHEMA_PATH = BASE_DIR / "schemas" / "config_schema.yml"

logger = logging.getLogger(__name__)


def parse_config_to_model(config_fname, add_config_dict=None):
    """
    Parses the config and model files and outputs python objects to be passed into run stardis so they can be individually modified in python.

    Parameters
    ----------
    config_fname : str
        Filepath to the STARDIS configuration. Must be a YAML file.
        add_config_keys : list, optional
        List of additional keys to add or overwrite for the configuration file.
    add_config_vals : list, optional
        List of corresponding additional values to add to the configuration file.

    Returns
    -------
    config : stardis.io.configuration.config_reader.Configuration
        Configuration object.
    adata : tardis.io.atom_data.AtomData
        AtomData object.
    stellar_model : stardis.io.model.marcs.MarcsModel or stardis.io.model.mesa.MesaModel
        Stellar model object.
    """

    try:
        config_dict = validate_yaml(config_fname, schemapath=SCHEMA_PATH)
        config = Configuration(config_dict)
    except:
        raise ValueError("Config failed to validate. Check the config file.")

    if (
        not add_config_dict
    ):  # If a dictionary was passed, update the config with the dictionary
        pass
    else:
        logger.info("Updating config with additional keys and values")
        for key, val in add_config_dict.items():
            try:
                config.set_config_item(key, val)
            except:
                raise ValueError(
                    f"{key} not a valid type. Should be a string for keys."
                )
        try:
            config_dict = validate_dict(config, schemapath=SCHEMA_PATH)
        except:
            raise ValueError("Additional config keys and values failed to validate.")

    adata = AtomData.from_hdf(config.atom_data)

    # model
    logger.info("Reading model")
    if config.input_model.type == "marcs":
        raw_marcs_model = read_marcs_model(
            Path(config.input_model.fname),
            gzipped=config.input_model.gzipped,
        )
        stellar_model = raw_marcs_model.to_stellar_model(
            adata,
            final_atomic_number=config.input_model.final_atomic_number,
            composition_source=config.input_model.composition_source,
            helium_mass_frac_Y=config.input_model.composition_Y,
            heavy_metal_mass_frac_Z=config.input_model.composition_Z,
        )
        if config.opacity.line.disable_microturbulence:
            stellar_model.microturbulence = stellar_model.microturbulence * 0.0

    elif config.input_model.type == "mesa":
        raw_mesa_model = read_mesa_model(Path(config.input_model.fname))
        if config.input_model.truncate_to_shell != -99:
            raw_mesa_model.truncate_model(config.input_model.truncate_to_shell)
        elif config.input_model.truncate_to_shell < 0:
            raise ValueError(
                f"{config.input_model.truncate_to_shell} shells were requested for mesa model truncation. -99 is default for no truncation."
            )

        stellar_model = raw_mesa_model.to_stellar_model(
            adata, final_atomic_number=config.input_model.final_atomic_number
        )

    else:
        raise ValueError("Model type not recognized. Must be either 'marcs' or 'mesa'")

    # Handle case of when there are fewer elements requested vs. elements in the atomic mass fraction table.
    adata.prepare_atom_data(
        np.arange(
            1,
            np.min(
                [
                    len(stellar_model.composition.elemental_mass_fraction),
                    config.input_model.final_atomic_number,
                ]
            )
            + 1,
        ),
        line_interaction_type="macroatom",
        nlte_species=[],
        continuum_interaction_species=[],
    )

    if (
        not config.input_model.nuclide_rescaling_dict
    ):  # Pass if no rescaling is requested, else rescale by dictionary values provided
        pass
    else:
        stellar_model.composition.nuclide_mass_fraction = (
            rescale_nuclide_mass_fractions(
                stellar_model.composition.nuclide_mass_fraction,
                list(config.input_model.nuclide_rescaling_dict.keys()),
                list(config.input_model.nuclide_rescaling_dict.values()),
            )
        )

    return config, adata, stellar_model
