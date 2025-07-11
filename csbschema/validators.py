from __future__ import annotations

import sys
import mmap
import json
from pathlib import Path
from typing import Tuple, Union, List, Optional
from collections.abc import Callable
import re
from importlib import resources

import jsonschema
from jsonschema import Draft202012Validator

ID_NUMBER_MMSI_RE = re.compile(r"^\d{9}$")
ID_NUMBER_IMO_RE = re.compile(r"^IMO\d{7}$")
ID_NUMBER_RE = {'MMSI': ID_NUMBER_MMSI_RE,
                'IMO': ID_NUMBER_IMO_RE}


def _error_factory(path: str, message: str) -> dict:
    return {'path': path, 'message': message}


def _validate_return(document: dict, errors: List[dict]) -> Tuple[bool, dict]:
    if len(errors) == 0:
        return True, {'document': document}
    else:
        return False, {'document': document, 'errors': errors}


def _get_schema_file(resource_path: str) -> Path:
    if sys.version_info[0] == 3 and sys.version_info[1] < 9:
        # Python version is less than 3.9, so use older method of resolving resource files
        with resources.path('csbschema.data', resource_path) as schema_file:
            return schema_file
    else:
        # Python version is >= 3.9, so use newer, non-deprecated resource resolution method
        return Path(str(resources.files('csbschema').joinpath(f"data/{resource_path}")))


def _get_validator(schema_rsrc_name: str) -> Draft202012Validator:
    """
    :param schema_rsrc_name: Internal resource name of schema document to use for validation
    :return: Draft202012Validator instance
    """
    schema_path = _get_schema_file(schema_rsrc_name)
    with schema_path.open('r', encoding='utf8') as f:
        schema = json.load(f)
    return jsonschema.Draft202012Validator(schema)


def _open_document(document_path: Union[Path, str]) -> Union[dict, list]:
    with open(document_path, 'rb') as f:
        with mmap.mmap(f.fileno(), length=0, access=mmap.ACCESS_READ) as mm:
            return json.load(mm)


def _get_properties(document: dict, errors: List, *,
                    not_found_mesg: Optional[str] = None) -> Optional[dict]:
    if 'properties' not in document:
        mesg = not_found_mesg
        if mesg is None:
            mesg = "'properties' property is needed for semantic validation, but was not found."
        errors.append(_error_factory('/',
                                     mesg))
        return None
    return document['properties']


def _get_properties_processing(properties: dict, errors: List, *,
                               not_found_mesg: Optional[str] = None,
                               context_path: str = '/properties') -> Optional[dict]:
    if 'processing' not in properties:
        mesg = not_found_mesg
        if mesg is None:
            mesg = "'processing' property is needed for semantic validation, but was not found."
        errors.append(_error_factory(context_path,
                                     mesg))
        return None
    return properties['processing']


def _get_properties_obs_coll_processing(properties: dict, errors: List, *,
                                        not_found_mesg: Optional[str] = None) -> Optional[dict]:
    if 'observationCollection' not in properties:
        mesg = not_found_mesg
        if mesg is None:
            mesg = "'observationCollection' property is needed for semantic validation, but was not found."
        errors.append(_error_factory('/properties',
                                     mesg))
        return None

    observationCollection = properties['observationCollection']

    return _get_properties_processing(properties['observationCollection'], errors,
                                      context_path='/properties/observationCollection')


def _get_lineage(document: dict, errors: List, *,
                 not_found_mesg: Optional[str] = None) -> Optional[dict]:
    if 'lineage' not in document:
        mesg = not_found_mesg
        if mesg is None:
            mesg = "'lineage' property is needed for semantic validation, but was not found."
        errors.append(_error_factory('/',
                                     mesg))
        return None
    return document['lineage']


def _get_features(document: dict, errors: List, *,
                  not_found_mesg: Optional[str] = None) -> Optional[dict]:
    if 'features' not in document:
        mesg = not_found_mesg
        if mesg is None:
            mesg = "'features' property is needed for semantic validation, but was not found."
        errors.append(_error_factory('/',
                                     mesg))
        return None
    return document['features']


def validate_b12_3_0_0_properties(document: dict, errors: List) -> None:
    """
    Do custom semantic validation on metadata properties
    """
    properties: dict = _get_properties(document, errors)
    if properties is None:
        return None

    if 'platform' not in properties:
        return None

    # There is 'platform' metadata, in which case we'll want to do some custom validation
    platform = properties['platform']
    # Custom validation for Platform.IDNumber, which depends on Platform.IDType
    id_type_present = False
    id_num_present = False
    if 'IDType' in platform:
        id_type_present = True
    if 'IDNumber' in platform:
        id_num_present = True

    if id_type_present and not id_num_present:
        errors.append(_error_factory('/properties/platform',
                                     "'IDNumber' attribute not present, but 'IDType' was specified."))
    elif id_num_present and not id_type_present:
        errors.append(_error_factory('/properties/platform',
                                     "'IDType' attribute not present, but 'IDNumber' was specified."))
    if id_type_present and id_num_present:
        id_type = platform['IDType']
        id_number = str(platform['IDNumber'])
        if id_type == 'IMO':
            # Use the same
            id_number = f"IMO{id_number}"
        try:
            if not ID_NUMBER_RE[id_type].match(id_number):
                errors.append(_error_factory('/properties/platform/IDNumber',
                                             f"IDNumber {platform['IDNumber']} is not valid for IDType {id_type}."))
        except KeyError:
            errors.append(_error_factory('/properties/platform/IDType',
                                         f"Unknown IDType {id_type}."))


def validate_b12_3_0_0_features(document: dict, errors: List) -> None:
    """

    """
    features = _get_features(document, errors)
    if features is None:
        return

    # Look for presence of uncertainty in any datum, if present, make sure Uncertainty processing metadata
    # element is also present
    uncert_present = False
    first_feature_with_uncert = 0
    for f in features:
        if 'uncertainty' in f['properties']:
            uncert_present = True
            break
        first_feature_with_uncert += 1
    if uncert_present:
        properties: dict = _get_properties(document, errors)
        if properties is None:
            return

        error_mesg: str = 'Observation uncertainty found, but Uncertainty metadata was not found.'
        uncert_meta_present = False
        lineage: dict = _get_lineage(document, errors)
        if lineage is not None:
            for l in lineage:
                if l['type'] == 'Uncertainty':
                    uncert_meta_present = True
                    break
        if not uncert_meta_present:
            errors.append(_error_factory(f"/features/{first_feature_with_uncert}/properties",
                                         error_mesg))


def validate_b12_3_0_0(schema_rsrc_name: str,
                       document_path: Union[Path, str], *,
                       validate_uncertainty: bool = True) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.0.0 CSB data and metadata against JSON schema
    :param schema_rsrc_name: Internal resource name of schema document to use for validation
    :param document_path: The document to validate
    :param validate_uncertainty: Boolean flag controlling whether uncertainty metadata should be validated.
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    validator = _get_validator(schema_rsrc_name)
    document = _open_document(document_path)

    errors = []
    for e in validator.iter_errors(document):
        # Basic validation against schema failed, note the failures, but allow validation to continue
        errors.append(_error_factory('/' + '/'.join([str(elem) for elem in e.absolute_path]),
                                     e.message))

    # Do custom "semantic" validation that is difficult/not possible to express in JSON schema
    validate_b12_3_0_0_properties(document, errors)
    if validate_uncertainty:
        validate_b12_3_0_0_features(document, errors)

    return _validate_return(document, errors)


def validate_b12_3_0_0_2023_03(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.0.0 CSB data and metadata against 2023-03 JSON schema
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_3_0_0('CSB-schema-3_0_0-2023-03.json', document_path,
                              validate_uncertainty=False)


def validate_b12_3_0_0_2023_08(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.0.0 CSB data and metadata against 2023-08 JSON schema
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_3_0_0('CSB-schema-3_0_0-2023-08.json', document_path)


def validate_b12_xyz_3_0_0(schema_rsrc_name: str,
                           document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.0.0 CSB XYZ metadata against JSON schema
    :param schema_rsrc_name: Internal resource name of schema document to use for validation
    :param document_path: The document to validate
    :param validator:
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    validator = _get_validator(schema_rsrc_name)
    document = _open_document(document_path)

    errors = []
    for e in validator.iter_errors(document):
        # Basic validation against schema failed, note the failures, but allow validation to continue
        errors.append(_error_factory('/' + '/'.join([str(elem) for elem in e.absolute_path]),
                                     e.message))

    if 'platform' not in document:
        errors.append(_error_factory('/',
                                     "'platform' is a required property."))
        return _validate_return(document, errors)

    platform = document['platform']
    # Custom validation for Platform.IDNumber, which depends on Platform.IDType
    id_type_present = False
    id_num_present = False
    if 'IDType' in platform:
        id_type_present = True
    if 'IDNumber' in platform:
        id_num_present = True

    if id_type_present and not id_num_present:
        errors.append(_error_factory('/platform',
                                     "'IDNumber' attribute not present, but 'IDType' was specified."))
    elif id_num_present and not id_type_present:
        errors.append(_error_factory('/platform',
                                     "'IDType' attribute not present, but 'IDNumber' was specified."))
    if id_type_present and id_num_present:
        id_type = platform['IDType']
        id_number = str(platform['IDNumber'])
        if id_type == 'IMO':
            # Use the same
            id_number = f"IMO{id_number}"
        try:
            if not ID_NUMBER_RE[id_type].match(id_number):
                errors.append(_error_factory('/platform/IDNumber',
                                             f"IDNumber {platform['IDNumber']} is not valid for IDType {id_type}."))
        except KeyError:
            errors.append(_error_factory('/platform/IDType',
                          f"Unknown IDType {id_type}."))

    return _validate_return(document, errors)


def validate_b12_xyz_3_0_0_2023_03(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.0.0 CSB XYZ metadata against 2023-03 JSON schema. Note: this validates
    metadata only, and is intended for use with metadata JSON files that are separate from CSB
    data provided in CSV or other file types.
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_xyz_3_0_0('XYZ-CSB-schema-3_0_0-2023-03.json', document_path)


def validate_b12_xyz_3_0_0_2023_08(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.0.0 CSB XYZ metadata against 2023-03 JSON schema. Note: this validates
    metadata only, and is intended for use with metadata JSON files that are separate from CSB
    data provided in CSV or other file types.
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_xyz_3_0_0('XYZ-CSB-schema-3_0_0-2023-08.json', document_path)


def validate_b12_3_1_0_platform(properties: dict, errors: List, *,
                                context_path: str = '/properties') -> None:
    """
    Do custom semantic validation on metadata properties
    """
    # There is 'platform' metadata, in which case we'll want to do some custom validation
    platform = properties['platform']
    # Custom validator for Platform.IDNumber, which depends on Platform.IDType
    if 'IDNumber' in platform:
        if 'IDType' not in platform:
            errors.append(_error_factory(f"{context_path}/platform",
                                         ("'IDType' attribute is not present, "
                                          "but must be as attribute 'IDNumber' is present.")
                                         ))
        else:
            # IDNumber and IDType are specified, validate that IDNumber is of type IDType
            id_type = platform['IDType']
            id_number = platform['IDNumber']
            try:
                if not ID_NUMBER_RE[id_type].match(id_number):
                    errors.append(_error_factory(f"{context_path}/platform/IDNumber",
                                                 f"IDNumber {id_number} is not valid for IDType {id_type}."))
            except KeyError:
                errors.append(_error_factory(f"{context_path}/platform/IDType",
                                             f"Unknown IDType {id_type}."))
    elif 'IDType' in platform:
        errors.append(_error_factory(f"{context_path}/platform",
                                     "'IDType' was specified but 'IDNumber' was not."))

    # Add custom validator for Platform.dataProcessed, which if False, Processing entries should not be present.
    data_processed = platform.get('dataProcessed', False)
    if data_processed:
        # dataProcessed is True, so "processing" entry ought to be present
        if 'processing' not in properties:
            errors.append(_error_factory(f"{context_path}/platform/dataProcessed",
                                         f"dataProcessed flag is 'true', but 'processing' properties were not found."))
    else:
        # dataProcessed is False, so "processing" entry should not be present
        if 'processing' in properties:
            errors.append(_error_factory(f"{context_path}/platform/dataProcessed",
                                         f"dataProcessed flag is 'false', but 'processing' properties were found."))
    if 'uniqueID' in platform:
        # 'uniqueID' can be present in platform as a duplicate of the required element 'uniqueVesselID` in
        # trustedNode. This is necessary to provide backward compatibility with DCDB ingest processing.
        if platform['uniqueID'] != properties['trustedNode']['uniqueVesselID']:
            errors.append(_error_factory(f"{context_path}/platform/uniqueID",
                                         f"uniqueID: {platform['uniqueID']} "
                                         f"does not match {context_path}/trustedNode/uniqueVesselID: "
                                         f"{properties['trustedNode']['uniqueVesselID']}"))


def validate_b12_3_1_0_properties(document: dict, errors: List) -> None:
    """
    Do custom semantic validation on metadata properties
    """
    properties: dict = _get_properties(document, errors)
    if properties is None:
        return

    if 'platform' not in properties:
        return

    if 'trustedNode' not in properties:
        return

    if 'uniqueVesselID' not in properties['trustedNode']:
        errors.append(_error_factory('/properties/trustedNode',
                                     "'uniqueVesselID' is a required property."))
        return

    validate_b12_3_1_0_platform(properties, errors)


def validate_b12_xyz_3_1_0_properties(document: dict, errors: List) -> None:
    """
    Do custom semantic validation on metadata properties
    """
    if 'platform' not in document:
        return

    validate_b12_3_1_0_platform(document, errors, context_path='')


def validate_b12_3_1_0_plus_features(document: dict, errors: List,
                                     get_processing_meta: Callable[[dict, list], Optional[dict]] = \
                                             _get_properties_processing) -> None:
    """
    Do custom semantic validation on features for B12 v. 3.1.0, 3.2.0-BETA, and later
    """

    features = _get_features(document, errors)
    if features is None:
        return

    # Look for presence of uncertainty in any datum, if present, make sure Uncertainty processing metadata
    # element is also present
    uncert_present = False
    first_feature_with_uncert = 0
    for f in features:
        if 'uncertainty' in f['properties']:
            uncert_present = True
            break
        first_feature_with_uncert += 1
    if uncert_present:
        properties: dict = _get_properties(document, errors)
        if properties is None:
            return

        error_mesg: str = 'Observation uncertainty found, but Uncertainty metadata was not found.'
        uncert_meta_present = False
        processing: dict = get_processing_meta(properties, errors)
        if processing is not None:
            for p in processing:
                if p['type'] == 'Uncertainty':
                    uncert_meta_present = True
                    break
        if not uncert_meta_present:
            errors.append(_error_factory(f"/features/{first_feature_with_uncert}/properties",
                                         error_mesg))


def validate_b12_3_1_0(schema_rsrc_name: str,
                       document_path: Union[Path, str], *,
                       validate_uncertainty: bool = True) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.1.0 CSB data and metadata against JSON schema
    :param schema_rsrc_name: Internal resource name of schema document to use for validation
    :param document_path: The document to validate
    :param validate_uncertainty: Boolean flag controlling whether uncertainty metadata should be validated.
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    validator = _get_validator(schema_rsrc_name)
    document = _open_document(document_path)

    # Do "structural" validation using jsonschema and capture all errors encountered
    errors = []
    for e in validator.iter_errors(document):
        # Basic validation against schema failed, note the failures, but allow validation to continue
        errors.append(_error_factory('/' + '/'.join([str(elem) for elem in e.absolute_path]),
                                     e.message))

    # Do custom "semantic" validation that is difficult/not possible to express in JSON schema
    validate_b12_3_1_0_properties(document, errors)
    if validate_uncertainty:
        validate_b12_3_1_0_plus_features(document, errors)

    return _validate_return(document, errors)


def validate_b12_xyz_3_1_0(schema_rsrc_name: str,
                           document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.1.0 CSB data and metadata against JSON schema
    :param schema_rsrc_name: Internal resource name of schema document to use for validation
    :param document_path: The document to validate
    :param validate_uncertainty: Boolean flag controlling whether uncertainty metadata should be validated.
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    validator = _get_validator(schema_rsrc_name)
    document = _open_document(document_path)

    # Do "structural" validation using jsonschema and capture all errors encountered
    errors = []
    for e in validator.iter_errors(document):
        # Basic validation against schema failed, note the failures, but allow validation to continue
        errors.append(_error_factory('/' + '/'.join([str(elem) for elem in e.absolute_path]),
                                     e.message))

    # Do custom "semantic" validation that is difficult/not possible to express in JSON schema
    validate_b12_xyz_3_1_0_properties(document, errors)

    return _validate_return(document, errors)


def validate_b12_3_1_0_2023_03(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.1.0 CSB data and metadata against 2023-03 JSON schema
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_3_1_0('CSB-schema-3_1_0-2023-03.json', document_path,
                              validate_uncertainty=False)


def validate_b12_3_1_0_2024_04(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.1.0 CSB data and metadata against 2024-04 JSON schema
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_3_1_0('CSB-schema-3_1_0-2024-04.json', document_path)


def validate_b12_3_1_0_2023_08(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.1.0 CSB data and metadata against 2023-08 JSON schema
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_3_1_0('CSB-schema-3_1_0-2023-08.json', document_path)


def validate_b12_xyz_3_1_0_2024_04(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.1.0 CSB XYZ metadata against 2024-04 JSON schema
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_xyz_3_1_0('XYZ-CSB-schema-3_1_0-2024-04.json', document_path)


def validate_b12_xyz_3_1_0_2023_08(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.1.0 CSB XYZ metadata against 2023-08 JSON schema
    :param document_path: The document to validate
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_xyz_3_1_0('XYZ-CSB-schema-3_1_0-2023-08.json', document_path)


def validate_b12_3_2_0_properties(document: dict, errors: List) -> None:
    properties: dict = _get_properties(document, errors)
    if properties is None:
        return None

    # See if there is 'trustedNodePlatform' metadata, in which case we'll want to do some custom validation
    if 'trustedNodePlatform' in properties:
        tnp = properties['trustedNodePlatform']
        # Custom validator for trustedNodePlatform/IDNumber, which depends on trustedNodePlatform/IDType
        if 'IDType' not in tnp:
            errors.append(_error_factory('/properties/trustedNodePlatform',
                                         "'IDType' attribute not present, but must be."))
        id_type = tnp['IDType']
        if 'IDNumber' not in tnp:
            errors.append(_error_factory('/properties/trustedNodePlatform',
                                         "'IDNumber' attribute not present, but must be."))
        id_number = tnp['IDNumber']
        try:
            if not ID_NUMBER_RE[id_type].match(id_number):
                errors.append(_error_factory('/properties/trustedNodePlatform/IDNumber',
                                             f"IDNumber {id_number} is not valid for IDType {id_type}."))
        except KeyError:
            errors.append(_error_factory('/properties/trustedNodePlatform/IDType',
                                         f"Unknown IDType {id_type}."))

    if 'observationCollection' in properties:
        obs_coll = properties['observationCollection']
        if 'platform' in obs_coll:
            platform = obs_coll['platform']
            # Add custom validator for Platform.dataProcessed, which if False, Processing entries should not be present.
            data_processed = platform.get('dataProcessed', False)
            if data_processed:
                # dataProcessed is True, so "processing" entry ought to be present
                if 'processing' not in obs_coll:
                    errors.append(_error_factory('/properties/observationCollection/platform',
                                                 ("dataProcessed flag is 'true', but "
                                                  "'/properties/observationCollection/processing' "
                                                  "properties were NOT found."))
                                  )
            else:
                # dataProcessed is False, so "processing" observation collection entry should not be present
                if 'processing' in obs_coll:
                    errors.append(_error_factory('/properties/observationCollection/platform',
                                                 ("dataProcessed flag is 'false', but "
                                                  "'/properties/observationCollection/processing' "
                                                  "properties were found."))
                                  )


def validate_b12_3_2_0(schema_rsrc_name: str,
                       document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.2.0 CSB data and metadata against JSON schema
    :param schema_rsrc_name: Internal resource name of schema document to use for validation
    :param document_path: The document to validate
    :param validator:
    :return: Tuple[bool, dict]. If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    validator = _get_validator(schema_rsrc_name)
    document = _open_document(document_path)

    valid = True
    result = {'document': document}

    errors = []
    result['errors'] = errors
    for e in validator.iter_errors(document):
        # Basic validation against schema failed, note the failures, but allow validation to continue
        errors.append(_error_factory('/' + '/'.join([str(elem) for elem in e.absolute_path]),
                                     e.message))

    # Do custom "semantic" validation that is difficult/not possible to express in JSON schema
    validate_b12_3_2_0_properties(document, errors)
    validate_b12_3_1_0_plus_features(document, errors,
                                     get_processing_meta=_get_properties_obs_coll_processing)

    return _validate_return(document, errors)


def validate_b12_3_2_0_BETA(document_path: Union[Path, str]) -> Tuple[bool, dict]:
    """
    Validate B12 version 3.2.0-BETA CSB data and metadata against BETA JSON schema
    :param document_path: The document to validate
    :return: If bool is True (which signals that validation succeeded), then dict will contain
        a single key 'document' whose value is a dict representing the document that was validated. If bool is False
        (which signals that validation failed), then dict will contain two keys: (1) 'document' whose value
        is a dict representing the document that failed validation; and (2) 'errors' whose value is a list
        of dicts mapping JSON path elements to errors encountered at that element.
    """
    return validate_b12_3_2_0('CSB-schema-3_2_0-BETA.json', document_path)
