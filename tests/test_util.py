import sys
import os
import asyncio
import meshctrl

test_dict = {
    "string": "string",
    "int": 1,
    "list": [1,2,3,4],
    "set": [1,2,3,4],
    "dict": {
        "string": "string",
        "int": 1,
        "list": [1,2,3,4],
        "set": [1,2,3,4]
    }
}

def compare_dict(d):
    assert meshctrl.util.compare_dict(d["dict"], test_dict) == d["equal"], f"dict equality incorrect: isequal: {not d['equal']} {d['dict']} {test_dict}"

def test_compare_dict_string_equals():
    compare_dict({
        "equal": True, 
        "dict": {
            "string": "string"
        }
    })

def test_compare_dict_int_equals():
    compare_dict({
        "equal": True, 
        "dict": {
            "int": 1
        }
    })

def test_compare_dict_list_equals():
    compare_dict({
        "equal": True, 
        "dict": {
            "list": [1,2,3,4]
        }
    })

def test_compare_dict_set_equals():
    compare_dict({
        "equal": True, 
        "dict": {
            "set": set([1,3])
        }
    })

def test_compare_dict_dict_equals():
    compare_dict({
        "equal": True, 
        "dict": {
            "dict": {
                "string": "string"
            }
        }
    })

def test_compare_dict_string_not_equals():
    compare_dict({
        "equal": False, 
        "dict": {
            "string": "string2"
        }
    })

def test_compare_dict_int_not_equals():
    compare_dict({
        "equal": False, 
        "dict": {
            "int": 2
        }
    })

def test_compare_dict_list_not_equals_order():
    compare_dict({
        "equal": False, 
        "dict": {
            "list": [1,2,4,3]
        }
    })

def test_compare_dict_list_not_equals_length_long():
    compare_dict({
        "equal": False, 
        "dict": {
            "list": [1,2,3,4,5]
        }
    })

def test_compare_dict_list_not_equals_length_short():
    compare_dict({
        "equal": False, 
        "dict": {
            "list": [1,2,3]
        }
    })

def test_compare_dict_set_not_equals():
    compare_dict({
        "equal": False, 
        "dict": {
            "set": set([6])
        }
    })

def test_compare_dict_string_not_equals_list():
    compare_dict({
        "equal": False, 
        "dict": {
            "string": ['s', 't', 'r', 'i', 'n', 'g']
        }
    })

def test_compare_dict_dict_not_equals_value():
    compare_dict({
        "equal": False, 
        "dict": {
            "dict": {
                "string": "string2"
            }
        }
    })

def test_compare_dict_dict_not_equals_key():
    compare_dict({
        "equal": False, 
        "dict": {
            "dict": {
                "string2": "string"
            }
        }
    })