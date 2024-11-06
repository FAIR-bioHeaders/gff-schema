import os
import re
from collections import defaultdict
from linkml_runtime.linkml_model.meta import SchemaDefinition, ClassDefinition, SlotDefinition, ClassDefinitionName, SlotDefinitionName
from linkml_runtime.utils.schemaview import SchemaView
from linkml_runtime.utils.yamlutils import YAMLRoot

class GFF3Validator:
    """
    Validates GFF3 files against the GFF3 specification.
    
    This validator is based on the GFF3 schema defined in the biodatamodels/gff-schema repository
    (https://raw.githubusercontent.com/biodatamodels/gff-schema/refs/heads/main/python/gff.py)
    and the validation features from the tharris/gff3_validator repository
    (https://raw.githubusercontent.com/tharris/gff3_validator/refs/heads/master/lib/GFF3/Validator.pm).
    """
    
    def __init__(self, schema_path=None):
        if schema_path is None:
            schema_path = os.path.join(os.path.dirname(__file__), 'gff.py')
        self.schema_view = SchemaView(schema_path)
        self.class_definitions = {name: self.schema_view.get_class(name) for name in self.schema_view.all_class_names()}
        self.slot_definitions = {name: self.schema_view.get_slot(name) for name in self.schema_view.all_slot_names()}
        self.seen_ids = set()
        self.parent_relationships = defaultdict(list)
        self.feature_types = set()
    
    def validate_line(self, line_number, line):
        """
        Validate a single line of a GFF3 file.
        
        Args:
            line_number (int): The line number of the GFF3 file.
            line (str): A single line of a GFF3 file.
        
        Returns:
            dict: A dictionary containing validation errors, if any.
        """
        fields = line.strip().split('\t')
        if len(fields) != 9:
            return {'error': 'Line must have 9 tab-separated fields'}
        
        seqid, source, type, start, end, score, strand, phase, attributes = fields
        
        errors = {}
        
        # Validate seqid
        if not self.schema_view.has_class('Seqid') or not self.class_definitions['Seqid'].typeof(seqid):
            errors['seqid'] = f'Invalid seqid: {seqid}'
        
        # Validate source
        if not self.schema_view.has_class('Source') or not self.class_definitions['Source'].typeof(source):
            errors['source'] = f'Invalid source: {source}'
        
        # Validate type
        if not self.schema_view.has_class('Type') or not self.class_definitions['Type'].typeof(type):
            errors['type'] = f'Invalid type: {type}'
        else:
            self.feature_types.add(type)
        
        # Validate start and end
        try:
            start_int = int(start)
            end_int = int(end)
            if start_int < 1:
                errors['start'] = f'Start position must be >= 1: {start}'
            if end_int < start_int:
                errors['end'] = f'End position must be >= start position: {end}'
        except ValueError:
            errors['start'] = f'Invalid start position: {start}'
            errors['end'] = f'Invalid end position: {end}'
        
        # Validate score
        if score != '.' and (not self.schema_view.has_slot('score') or not self.slot_definitions['score'].typeof(score)):
            errors['score'] = f'Invalid score: {score}'
        
        # Validate strand
        if strand not in ['+', '-', '.']:
            errors['strand'] = f'Invalid strand: {strand}'
        
        # Validate phase
        if phase != '.' and (not self.schema_view.has_slot('phase') or not self.slot_definitions['phase'].typeof(phase)):
            errors['phase'] = f'Invalid phase: {phase}'
        
        # Validate attributes
        attr_dict = {}
        for attr in attributes.split(';'):
            if '=' in attr:
                key, value = attr.split('=', 1)
                attr_dict[key] = value
            else:
                attr_dict[attr] = True
        
        for key, value in attr_dict.items():
            if not self.schema_view.has_slot(key) or not self.slot_definitions[key].typeof(value):
                errors[f'attribute.{key}'] = f'Invalid attribute: {key}={value}'
        
        # Additional validation checks from the Perl validator
        
        # Check for duplicate IDs
        if 'ID' in attr_dict:
            id_value = attr_dict['ID']
            if id_value in self.seen_ids:
                errors['id'] = f'Duplicate ID: {id_value}'
            else:
                self.seen_ids.add(id_value)
        
        # Check for invalid characters in IDs
        if 'ID' in attr_dict:
            id_value = attr_dict['ID']
            if not re.match(r'^[a-zA-Z0-9.:^*$@!+_?-]+$', id_value):
                errors['id'] = f'Invalid characters in ID: {id_value}'
        
        # Check for invalid Parent relationships
        if 'Parent' in attr_dict:
            parent_ids = attr_dict['Parent'].split(',')
            for parent_id in parent_ids:
                if parent_id not in self.seen_ids:
                    errors.setdefault('parent', []).append(f'Parent ID not found: {parent_id}')
                self.parent_relationships[parent_id].append(id_value)
        
        # Check for circular references in Parent relationships
        if 'Parent' in attr_dict:
            parent_ids = attr_dict['Parent'].split(',')
            for parent_id in parent_ids:
                if parent_id in self.parent_relationships and id_value in self.parent_relationships[parent_id]:
                    errors.setdefault('parent', []).append(f'Circular reference detected for ID: {id_value}')
        
        # Check for invalid Alias values
        if 'Alias' in attr_dict:
            alias_values = attr_dict['Alias'].split(',')
            for alias_value in alias_values:
                if not re.match(r'^[a-zA-Z0-9.:^*$@!+_?-]+$', alias_value):
                    errors.setdefault('alias', []).append(f'Invalid characters in Alias: {alias_value}')
        
        # Check for invalid Note values
        if 'Note' in attr_dict:
            note_values = attr_dict['Note'].split(',')
            for note_value in note_values:
                if not note_value:
                    errors.setdefault('note', []).append('Empty Note value')
        
        # Check for invalid Target values
        if 'Target' in attr_dict:
            target_values = attr_dict['Target'].split()
            if len(target_values) < 3:
                errors.setdefault('target', []).append(f'Invalid Target attribute: {attr_dict["Target"]}')
            else:
                target_id, target_start, target_end = target_values[:3]
                if target_id not in self.seen_ids:
                    errors.setdefault('target', []).append(f'Target ID not found: {target_id}')
                try:
                    target_start_int = int(target_start)
                    target_end_int = int(target_end)
                    if target_start_int < 1:
                        errors.setdefault('target', []).append(f'Target start position must be >= 1: {target_start}')
                    if target_end_int < target_start_int:
                        errors.setdefault('target', []).append(f'Target end position must be >= start position: {target_end}')
                except ValueError:
                    errors.setdefault('target', []).append('Invalid Target start or end position')
        
        # Check for invalid Derives_from values
        if 'Derives_from' in attr_dict:
            derives_from_values = attr_dict['Derives_from'].split(',')
            for derives_from_value in derives_from_values:
                if derives_from_value not in self.seen_ids:
                    errors.setdefault('derives_from', []).append(f'Derives_from ID not found: {derives_from_value}')
        
        # Check for invalid Gap values
        if 'Gap' in attr_dict:
            gap_values = attr_dict['Gap'].split()
            if len(gap_values) < 2:
                errors.setdefault('gap', []).append(f'Invalid Gap attribute: {attr_dict["Gap"]}')
            else:
                try:
                    gap_length = int(gap_values[0])
                    if gap_length < 0:
                        errors.setdefault('gap', []).append(f'Invalid Gap length: {gap_values[0]}')
                except ValueError:
                    errors.setdefault('gap', []).append(f'Invalid Gap length: {gap_values[0]}')
        
        # Check for invalid Replacement values
        if 'Replacement' in attr_dict:
            replacement_value = attr_dict['Replacement']
            if len(replacement_value) != 1:
                errors.setdefault('replacement', []).append(f'Invalid Replacement value: {replacement_value}')
        
        # Check for invalid Sequence attribute
        if 'Sequence' in attr_dict:
            sequence_value = attr_dict['Sequence']
            if not all(c in 'ACGTacgt' for c in sequence_value):
                errors.setdefault('sequence', []).append(f'Invalid characters in Sequence: {sequence_value}')
        
        # Check for invalid Variant_seq attribute
        if 'Variant_seq' in attr_dict:
            variant_seq_value = attr_dict['Variant_seq']
            if not all(c in 'ACGTacgt' for c in variant_seq_value):
                errors.setdefault('variant_seq', []).append(f'Invalid characters in Variant_seq: {variant_seq_value}')
        
        # Check for invalid Amino_acid attribute
        if 'Amino_acid' in attr_dict:
            amino_acid_value = attr_dict['Amino_acid']
            if not all(c in 'ACDEFGHIKLMNPQRSTVWYacdefghiklmnpqrstvwy*' for c in amino_acid_value):
                errors.setdefault('amino_acid', []).append(f'Invalid characters in Amino_acid: {amino_acid_value}')
        
        # Check for invalid Codon attribute
        if 'Codon' in attr_dict:
            codon_value = attr_dict['Codon']
            if len(codon_value) != 3 or not all(c in 'ACGTacgt' for c in codon_value):
                errors.setdefault('codon', []).append(f'Invalid Codon value: {codon_value}')
        
        return errors
    
    def validate_file(self, file_path):
        """
        Validate a GFF3 file.
        
        Args:
            file_path (str): The path to the GFF3 file.
        
        Returns:
            dict: A dictionary containing validation errors, if any.
        """
        errors = {}
        self.seen_ids = set()
        self.parent_relationships = defaultdict(list)
        self.feature_types = set()
        line_number = 1
        
        with open(file_path, 'r') as f:
            for line in f:
                if line.startswith('#'):
                    continue
                line_errors = self.validate_line(line_number, line)
                if line_errors:
                    errors.setdefault(line_number, {}).update(line_errors)
                line_number += 1
        
        # Check for unresolved Parent references
        for parent_id, child_ids in self.parent_relationships.items():
            if parent_id not in self.seen_ids:
                for child_id in child_ids:
                    errors.setdefault(child_id, {}).setdefault('parent', []).append(f'Parent ID not found: {parent_id}')
        
        # Check for duplicate feature types
        if len(self.feature_types) != len(self.class_definitions['Type'].permissible_values):
            missing_types = set(self.class_definitions['Type'].permissible_values) - self.feature_types
            errors['feature_type'] = f'Missing feature types: {", ".join(missing_types)}'
        
        return errors
