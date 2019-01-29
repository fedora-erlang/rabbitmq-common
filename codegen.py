#!/usr/bin/python3

## This Source Code Form is subject to the terms of the Mozilla Public
## License, v. 2.0. If a copy of the MPL was not distributed with this
## file, You can obtain one at https://mozilla.org/MPL/2.0/.
##
## Copyright (c) 2007-2020 VMware, Inc. or its affiliates.  All rights reserved.
##

from __future__ import nested_scopes
from __future__ import print_function

import sys

from amqp_codegen import *
import string
import re

# Coming up with a proper encoding of AMQP tables in JSON is too much
# hassle at this stage. Given that the only default value we are
# interested in is for the empty table, we only support that.
def convertTable(d):
    if len(d) == 0:
        return "[]"
    else:
        raise Exception('Non-empty table defaults not supported ' + d)

erlangDefaultValueTypeConvMap = {
    bool : lambda x: str(x).lower(),
    int : lambda x: str(x),
    float : lambda x: str(x),
    dict: convertTable
}

try:
    _checkIfPython2 = unicode
    erlangDefaultValueTypeConvMap[str] = lambda x: "<<\"" + x + "\">>"
    erlangDefaultValueTypeConvMap[unicode] = lambda x: "<<\"" + x.encode("utf-8") + "\">>"
except NameError:
    erlangDefaultValueTypeConvMap[bytes] = lambda x: "<<\"" + x + "\">>"
    erlangDefaultValueTypeConvMap[str] = lambda x: "<<\"" + x + "\">>"

def erlangize(s):
    s = s.replace('-', '_')
    s = s.replace(' ', '_')
    return s

AmqpMethod.erlangName = lambda m: "'" + erlangize(m.klass.name) + '.' + erlangize(m.name) + "'"

AmqpClass.erlangName = lambda c: "'" + erlangize(c.name) + "'"

def erlangConstantName(s):
    return '_'.join(re.split('[- ]', s.upper()))

class PackedMethodBitField:
    def __init__(self, index):
        self.index = index
        self.domain = 'bit'
        self.contents = []

    def extend(self, f):
        self.contents.append(f)

    def count(self):
        return len(self.contents)

    def full(self):
        return self.count() == 8

def multiLineFormat(things, prologue, separator, lineSeparator, epilogue, thingsPerLine = 4):
    r = [prologue]
    i = 0
    for t in things:
        if i != 0:
            if i % thingsPerLine == 0:
                r += [lineSeparator]
            else:
                r += [separator]
        r += [t]
        i += 1
    r += [epilogue]
    return "".join(r)

def prettyType(typeName, subTypes, typesPerLine = 4):
    """Pretty print a type signature made up of many alternative subtypes"""
    sTs = multiLineFormat(subTypes,
                          "( ", " | ", "\n       | ", " )",
                          thingsPerLine = typesPerLine)
    return "-type %s ::\n       %s." % (typeName, sTs)

def printFileHeader():
    print("""%%   Autogenerated code. Do not edit.
%%
%%  The contents of this file are subject to the Mozilla Public License
%%  Version 1.1 (the "License"); you may not use this file except in
%%  compliance with the License. You may obtain a copy of the License
%%  at https://www.mozilla.org/MPL/
%%
%%  Software distributed under the License is distributed on an "AS IS"
%%  basis, WITHOUT WARRANTY OF ANY KIND, either express or implied. See
%%  the License for the specific language governing rights and
%%  limitations under the License.
%%
%%  The Original Code is RabbitMQ.
%%
%%  The Initial Developer of the Original Code is Pivotal Software, Inc.
%%  Copyright (c) 2007-2020 VMware, Inc. or its affiliates.  All rights reserved.
%%""")

def genErl(spec):
    def erlType(domain):
        return erlangize(spec.resolveDomain(domain))

    def fieldTypeList(fields):
        return '[' + ', '.join([erlType(f.domain) for f in fields]) + ']'

    def fieldNameList(fields):
        return '[' + ', '.join([erlangize(f.name) for f in fields]) + ']'

    def fieldTempList(fields):
        return '[' + ', '.join(['F' + str(f.index) for f in fields]) + ']'

    def fieldMapList(fields):
        return ', '.join([erlangize(f.name) + " = F" + str(f.index) for f in fields])

    def genLookupMethodName(m):
        print("lookup_method_name({%d, %d}) -> %s;" % (m.klass.index, m.index, m.erlangName()))

    def genLookupClassName(c):
        print("lookup_class_name(%d) -> %s;" % (c.index, c.erlangName()))

    def genMethodId(m):
        print("method_id(%s) -> {%d, %d};" % (m.erlangName(), m.klass.index, m.index))

    def genMethodHasContent(m):
        print("method_has_content(%s) -> %s;" % (m.erlangName(), str(m.hasContent).lower()))

    def genMethodIsSynchronous(m):
        hasNoWait = "nowait" in fieldNameList(m.arguments)
        if m.isSynchronous and hasNoWait:
          print("is_method_synchronous(#%s{nowait = NoWait}) -> not(NoWait);" % (m.erlangName()))
        else:
          print("is_method_synchronous(#%s{}) -> %s;" % (m.erlangName(), str(m.isSynchronous).lower()))

    def genMethodFieldTypes(m):
        """Not currently used - may be useful in future?"""
        print("method_fieldtypes(%s) -> %s;" % (m.erlangName(), fieldTypeList(m.arguments)))

    def genMethodFieldNames(m):
        print("method_fieldnames(%s) -> %s;" % (m.erlangName(), fieldNameList(m.arguments)))

    def packMethodFields(fields):
        packed = []
        bitfield = None
        for f in fields:
            if erlType(f.domain) == 'bit':
                if not(bitfield) or bitfield.full():
                    bitfield = PackedMethodBitField(f.index)
                    packed.append(bitfield)
                bitfield.extend(f)
            else:
                bitfield = None
                packed.append(f)
        return packed

    def methodFieldFragment(f):
        type = erlType(f.domain)
        p = 'F' + str(f.index)
        if type == 'shortstr':
            return p+'Len:8/unsigned, '+p+':'+p+'Len/binary'
        elif type == 'longstr':
            return p+'Len:32/unsigned, '+p+':'+p+'Len/binary'
        elif type == 'octet':
            return p+':8/unsigned'
        elif type == 'short':
            return p+':16/unsigned'
        elif type == 'long':
            return p+':32/unsigned'
        elif type == 'longlong':
            return p+':64/unsigned'
        elif type == 'timestamp':
            return p+':64/unsigned'
        elif type == 'bit':
            return p+'Bits:8'
        elif type == 'table':
            return p+'Len:32/unsigned, '+p+'Tab:'+p+'Len/binary'

    def genFieldPostprocessing(packed, hasContent):
        for f in packed:
            type = erlType(f.domain)
            if type == 'bit':
                for index in range(f.count()):
                    print("  F%d = ((F%dBits band %d) /= 0)," % \
                          (f.index + index,
                           f.index,
                           1 << index))
            elif type == 'table':
                print("  F%d = rabbit_binary_parser:parse_table(F%dTab)," % \
                      (f.index, f.index))
            # We skip the check on content-bearing methods for
            # speed. This is a sanity check, not a security thing.
            elif type == 'shortstr' and not hasContent:
                print("  rabbit_binary_parser:assert_utf8(F%d)," % (f.index))
            else:
                pass

    def genMethodRecord(m):
        print("method_record(%s) -> #%s{};" % (m.erlangName(), m.erlangName()))

    def genDecodeMethodFields(m):
        packedFields = packMethodFields(m.arguments)
        binaryPattern = ', '.join([methodFieldFragment(f) for f in packedFields])
        if binaryPattern:
            restSeparator = ', '
        else:
            restSeparator = ''
        recordConstructorExpr = '#%s{%s}' % (m.erlangName(), fieldMapList(m.arguments))
        print("decode_method_fields(%s, <<%s>>) ->" % (m.erlangName(), binaryPattern))
        genFieldPostprocessing(packedFields, m.hasContent)
        print("  %s;" % (recordConstructorExpr,))

    def genDecodeProperties(c):
        def presentBin(fields):
            ps = ', '.join(['P' + str(f.index) + ':1' for f in fields])
            return '<<' + ps + ', _:%d, R0/binary>>' % (16 - len(fields),)
        def writePropFieldLine(field):
            i = str(field.index)
            if field.domain == 'bit':
                print("  {F%s, R%s} = {P%s =/= 0, R%s}," % \
                    (i, str(field.index + 1), i, i))
            else:
                print("  {F%s, R%s} = if P%s =:= 0 -> {undefined, R%s}; true -> ?%s_VAL(R%s, L%s, V%s, X%s) end," % \
                    (i, str(field.index + 1), i, i, erlType(field.domain).upper(), i, i, i, i))

        if len(c.fields) == 0:
            print("decode_properties(%d, <<>>) ->" % (c.index,))
        else:
            print(("decode_properties(%d, %s) ->" %
                   (c.index, presentBin(c.fields))))
            for field in c.fields:
                writePropFieldLine(field)
            print("  <<>> = %s," % ('R' + str(len(c.fields))))
        print("  #'P_%s'{%s};" % (erlangize(c.name), fieldMapList(c.fields)))

    def genFieldPreprocessing(packed):
        for f in packed:
            type = erlType(f.domain)
            if type == 'bit':
                print("  F%dBits = (%s)," % \
                      (f.index,
                       ' bor '.join(['(bitvalue(F%d) bsl %d)' % (x.index, x.index - f.index)
                                     for x in f.contents])))
            elif type == 'table':
                print("  F%dTab = rabbit_binary_generator:generate_table(F%d)," % (f.index, f.index))
                print("  F%dLen = size(F%dTab)," % (f.index, f.index))
            elif type == 'shortstr':
                print("  F%dLen = shortstr_size(F%d)," % (f.index, f.index))
            elif type == 'longstr':
                print("  F%dLen = size(F%d)," % (f.index, f.index))
            else:
                pass

    def genEncodeMethodFields(m):
        packedFields = packMethodFields(m.arguments)
        print("encode_method_fields(#%s{%s}) ->" % (m.erlangName(), fieldMapList(m.arguments)))
        genFieldPreprocessing(packedFields)
        print("  <<%s>>;" % (', '.join([methodFieldFragment(f) for f in packedFields])))

    def genEncodeProperties(c):
        def presentBin(fields):
            ps = ', '.join(['P' + str(f.index) + ':1' for f in fields])
            return '<<' + ps + ', 0:%d>>' % (16 - len(fields),)
        def writePropFieldLine(field):
            i = str(field.index)
            if field.domain == 'bit':
                print("  {P%s, R%s} = {F%s =:= 1, R%s}," % \
                    (i, str(field.index + 1), i, i))
            else:
                print("  {P%s, R%s} = if F%s =:= undefined -> {0, R%s}; true -> {1, [?%s_PROP(F%s, L%s) | R%s]} end," % \
                    (i, str(field.index + 1), i, i, erlType(field.domain).upper(), i, i, i))

        print("encode_properties(#'P_%s'{%s}) ->" % (erlangize(c.name), fieldMapList(c.fields)))
        if len(c.fields) == 0:
            print("  <<>>;")
        else:
            print("  R0 = [<<>>],")
            for field in c.fields:
                writePropFieldLine(field)
            print("  list_to_binary([%s | lists:reverse(R%s)]);" % \
                (presentBin(c.fields), str(len(c.fields))))

    def messageConstantClass(cls):
        # We do this because 0.8 uses "soft error" and 8.1 uses "soft-error".
        return erlangConstantName(cls)

    def genLookupException(c,v,cls):
        mCls = messageConstantClass(cls)
        if mCls == 'SOFT_ERROR': genLookupException1(c,'false')
        elif mCls == 'HARD_ERROR': genLookupException1(c, 'true')
        elif mCls == '': pass
        else: raise Exception('Unknown constant class' + cls)

    def genLookupException1(c,hardErrorBoolStr):
        n = erlangConstantName(c)
        print('lookup_amqp_exception(%s) -> {%s, ?%s, <<"%s">>};' % \
              (n.lower(), hardErrorBoolStr, n, n))

    def genAmqpException(c,v,cls):
        n = erlangConstantName(c)
        print('amqp_exception(?%s) -> %s;' % \
            (n, n.lower()))

    methods = spec.allMethods()

    printFileHeader()
    module = "rabbit_framing_amqp_%d_%d" % (spec.major, spec.minor)
    if spec.revision != 0:
        module = "%s_%d" % (module, spec.revision)
    if module == "rabbit_framing_amqp_8_0":
        module = "rabbit_framing_amqp_0_8"
    print("-module(%s)." % module)
    print("""-include("rabbit_framing.hrl").

-export([version/0]).
-export([lookup_method_name/1]).
-export([lookup_class_name/1]).

-export([method_id/1]).
-export([method_has_content/1]).
-export([is_method_synchronous/1]).
-export([method_record/1]).
-export([method_fieldnames/1]).
-export([decode_method_fields/2]).
-export([decode_properties/2]).
-export([encode_method_fields/1]).
-export([encode_properties/1]).
-export([lookup_amqp_exception/1]).
-export([amqp_exception/1]).

""")
    print("%% Various types")

    print("""-export_type([amqp_field_type/0, amqp_property_type/0,
              amqp_table/0, amqp_array/0, amqp_value/0,
              amqp_method_name/0, amqp_method/0, amqp_method_record/0,
              amqp_method_field_name/0, amqp_property_record/0,
              amqp_exception/0, amqp_exception_code/0, amqp_class_id/0]).

-type amqp_field_type() ::
      'longstr' | 'signedint' | 'decimal' | 'timestamp' |
      'unsignedbyte' | 'unsignedshort' | 'unsignedint' |
      'table' | 'byte' | 'double' | 'float' | 'long' |
      'short' | 'bool' | 'binary' | 'void' | 'array'.
-type amqp_property_type() ::
      'shortstr' | 'longstr' | 'octet' | 'short' | 'long' |
      'longlong' | 'timestamp' | 'bit' | 'table'.

-type amqp_table() :: [{binary(), amqp_field_type(), amqp_value()}].
-type amqp_array() :: [{amqp_field_type(), amqp_value()}].
-type amqp_value() :: binary() |    % longstr
                      integer() |   % signedint
                      {non_neg_integer(), non_neg_integer()} | % decimal
                      amqp_table() |
                      amqp_array() |
                      byte() |      % byte
                      float() |     % double
                      integer() |   % long
                      integer() |   % short
                      boolean() |   % bool
                      binary() |    % binary
                      'undefined' | % void
                      non_neg_integer(). % timestamp
""")

    print(prettyType("amqp_method_name()",
                     [m.erlangName() for m in methods]))
    print(prettyType("amqp_method()",
                     ["{%s, %s}" % (m.klass.index, m.index) for m in methods],
                     6))
    print(prettyType("amqp_method_record()",
                     ["#%s{}" % (m.erlangName()) for m in methods]))
    fieldNames = set()
    for m in methods:
        fieldNames.update([erlangize(f.name) for f in m.arguments])
    fieldNames = [f for f in fieldNames]
    fieldNames.sort()
    print(prettyType("amqp_method_field_name()",
                     fieldNames))
    print(prettyType("amqp_property_record()",
                     ["#'P_%s'{}" % erlangize(c.name) for c in spec.allClasses()]))
    print(prettyType("amqp_exception()",
                     ["'%s'" % erlangConstantName(c).lower() for (c, v, cls) in spec.constants]))
    print(prettyType("amqp_exception_code()",
                     ["%i" % v for (c, v, cls) in spec.constants]))
    classIds = set()
    for m in spec.allMethods():
        classIds.add(m.klass.index)
    print(prettyType("amqp_class_id()",
                     ["%i" % ci for ci in classIds]))
    print(prettyType("amqp_class_name()",
                     ["%s" % c.erlangName() for c in spec.allClasses()]))

    print("""
%% Method signatures
-spec version() -> {non_neg_integer(), non_neg_integer(), non_neg_integer()}.
-spec lookup_method_name(amqp_method()) -> amqp_method_name().
-spec lookup_class_name(amqp_class_id()) -> amqp_class_name().
-spec method_id(amqp_method_name()) -> amqp_method().
-spec method_has_content(amqp_method_name()) -> boolean().
-spec is_method_synchronous(amqp_method_record()) -> boolean().
-spec method_record(amqp_method_name()) -> amqp_method_record().
-spec method_fieldnames(amqp_method_name()) -> [amqp_method_field_name()].
-spec decode_method_fields(amqp_method_name(), binary()) ->
          amqp_method_record() | rabbit_types:connection_exit().
-spec decode_properties(non_neg_integer(), binary()) -> amqp_property_record().
-spec encode_method_fields(amqp_method_record()) -> binary().
-spec encode_properties(amqp_property_record()) -> binary().
-spec lookup_amqp_exception(amqp_exception()) ->
          {boolean(), amqp_exception_code(), binary()}.
-spec amqp_exception(amqp_exception_code()) -> amqp_exception().

bitvalue(true) -> 1;
bitvalue(false) -> 0;
bitvalue(undefined) -> 0.

shortstr_size(S) ->
    case size(S) of
        Len when Len =< 255 -> Len;
        _                   -> exit(method_field_shortstr_overflow)
    end.

-define(SHORTSTR_VAL(R, L, V, X),
        begin
            <<L:8/unsigned, V:L/binary, X/binary>> = R,
            {V, X}
        end).

-define(LONGSTR_VAL(R, L, V, X),
        begin
            <<L:32/unsigned, V:L/binary, X/binary>> = R,
            {V, X}
        end).

-define(SHORT_VAL(R, L, V, X),
        begin
            <<V:8/unsigned, X/binary>> = R,
            {V, X}
        end).

-define(LONG_VAL(R, L, V, X),
        begin
            <<V:32/unsigned, X/binary>> = R,
            {V, X}
        end).

-define(LONGLONG_VAL(R, L, V, X),
        begin
            <<V:64/unsigned, X/binary>> = R,
            {V, X}
        end).

-define(OCTET_VAL(R, L, V, X),
        begin
            <<V:8/unsigned, X/binary>> = R,
            {V, X}
        end).

-define(TABLE_VAL(R, L, V, X),
        begin
            <<L:32/unsigned, V:L/binary, X/binary>> = R,
            {rabbit_binary_parser:parse_table(V), X}
        end).

-define(TIMESTAMP_VAL(R, L, V, X),
        begin
            <<V:64/unsigned, X/binary>> = R,
            {V, X}
        end).

-define(SHORTSTR_PROP(X, L),
        begin
            L = size(X),
            if L < 256 -> <<L:8, X:L/binary>>;
               true    -> exit(content_properties_shortstr_overflow)
            end
        end).

-define(LONGSTR_PROP(X, L),
        begin
            L = size(X),
            <<L:32, X:L/binary>>
        end).

-define(OCTET_PROP(X, L),     <<X:8/unsigned>>).
-define(SHORT_PROP(X, L),     <<X:16/unsigned>>).
-define(LONG_PROP(X, L),      <<X:32/unsigned>>).
-define(LONGLONG_PROP(X, L),  <<X:64/unsigned>>).
-define(TIMESTAMP_PROP(X, L), <<X:64/unsigned>>).

-define(TABLE_PROP(X, T),
        begin
            T = rabbit_binary_generator:generate_table(X),
            <<(size(T)):32, T/binary>>
        end).
""")
    version = "{%d, %d, %d}" % (spec.major, spec.minor, spec.revision)
    if version == '{8, 0, 0}': version = '{0, 8, 0}'
    print("version() -> %s." % (version))

    for m in methods: genLookupMethodName(m)
    print("lookup_method_name({_ClassId, _MethodId} = Id) -> exit({unknown_method_id, Id}).")

    for c in spec.allClasses(): genLookupClassName(c)
    print("lookup_class_name(ClassId) -> exit({unknown_class_id, ClassId}).")

    for m in methods: genMethodId(m)
    print("method_id(Name) -> exit({unknown_method_name, Name}).")

    for m in methods: genMethodHasContent(m)
    print("method_has_content(Name) -> exit({unknown_method_name, Name}).")

    for m in methods: genMethodIsSynchronous(m)
    print("is_method_synchronous(Name) -> exit({unknown_method_name, Name}).")

    for m in methods: genMethodRecord(m)
    print("method_record(Name) -> exit({unknown_method_name, Name}).")

    for m in methods: genMethodFieldNames(m)
    print("method_fieldnames(Name) -> exit({unknown_method_name, Name}).")

    for m in methods: genDecodeMethodFields(m)
    print("decode_method_fields(Name, BinaryFields) ->")
    print("  rabbit_misc:frame_error(Name, BinaryFields).")

    for c in spec.allClasses(): genDecodeProperties(c)
    print("decode_properties(ClassId, _BinaryFields) -> exit({unknown_class_id, ClassId}).")

    for m in methods: genEncodeMethodFields(m)
    print("encode_method_fields(Record) -> exit({unknown_method_name, element(1, Record)}).")

    for c in spec.allClasses(): genEncodeProperties(c)
    print("encode_properties(Record) -> exit({unknown_properties_record, Record}).")

    for (c,v,cls) in spec.constants: genLookupException(c,v,cls)
    print("lookup_amqp_exception(Code) ->")
    print("  rabbit_log:warning(\"Unknown AMQP error code '~p'~n\", [Code]),")
    print("  {true, ?INTERNAL_ERROR, <<\"INTERNAL_ERROR\">>}.")

    for(c,v,cls) in spec.constants: genAmqpException(c,v,cls)
    print("amqp_exception(_Code) -> undefined.")

def genHrl(spec):
    def fieldNameList(fields):
        return ', '.join([erlangize(f.name) for f in fields])

    def fieldNameListDefaults(fields):
        def fillField(field):
            result = erlangize(field.name)
            if field.defaultvalue != None:
                conv_fn = erlangDefaultValueTypeConvMap[type(field.defaultvalue)]
                result += ' = ' + conv_fn(field.defaultvalue)
            return result
        return ', '.join([fillField(f) for f in fields])

    methods = spec.allMethods()

    printFileHeader()
    print("-define(PROTOCOL_PORT, %d)." % (spec.port))

    for (c,v,cls) in spec.constants:
        print("-define(%s, %s)." % (erlangConstantName(c), v))

    print("%% Method field records.")
    for m in methods:
        print("-record(%s, {%s})." % (m.erlangName(), fieldNameListDefaults(m.arguments)))

    print("%% Class property records.")
    for c in spec.allClasses():
        print("-record('P_%s', {%s})." % (erlangize(c.name), fieldNameList(c.fields)))


def generateErl(specPath):
    genErl(AmqpSpec(specPath))

def generateHrl(specPath):
    genHrl(AmqpSpec(specPath))

if __name__ == "__main__":
    do_main_dict({"header": generateHrl,
                  "body": generateErl})

