import os
from commands import *
from datapack import Advancement
from placer import CommandPlacer

class Scope:
    def __init__(self, namespace, tag_name, variables, block_pos, args={}, extern=[]):
        self.entity_tag = namespace + '_' + tag_name
        self.pos_util = namespace + '_' + tag_name + '_pos'
        self.namespace = namespace
        self.variables = variables
        self.mem_locs = {}
        self.tags = {}
        self.args = args
        self.func_names = set()
        self.extern = set(extern or [])
        assert all(type(c) == int for c in block_pos), \
        "Block position must be absolute (for now). Use --place-location"
        self.util_pos = '%d %d %d' % block_pos

    def variable(self, name, args=()):
        var = self.variables[name]
        if type(var) == tuple:
            var = var[0]
        return self.trim(self.namespace + '_' + var % args)

    def entity_local(self, name):
        if name in self.extern:
            return name
        name = 'el_%s' % name
        self.variables[name] = name
        return self.variable(name)

    def get_util_block(self):
        return self.util_pos

    def memory(self, orig):
        self.mem_locs[orig] = True
        return self.trim('%s_x%x' % (self.namespace, orig))

    def trim(self, obj_name):
        # Objective name length must be <= 16
        return obj_name[-16:]

    def custom_nbt_path(self, path):
        return 'ArmorItems[0].tag.' + path

    def get_objectives(self):
        objectives = []
        for name in self.variables:
            if type(self.variables[name]) == tuple:
                template, options = self.variables[name]
                for args in options:
                    if not type(args) in [tuple, list]:
                        args = (args,)
                    objectives.append(self.variable(name, *args))
            else:
                objectives.append(self.variable(name))
        for loc in self.mem_locs:
            objectives.append(self.memory(loc))
        return objectives

    def get_mem_locs(self):
        return self.mem_locs.keys()

    def function_name(self, name):
        if name not in self.func_names:
            raise NameError('Function name %r not found' % name)
        return '%s:%s' % (self.namespace, name)

    def add_function_names(self, names):
        self.func_names.update(names)

    def cmd_arg(self, param, val):
        if param == 'tag':
            if val not in self.tags:
                self.tags[val] = '%s_tag_%s' % (self.namespace, val)
            return self.tags[val]
        elif param == 'arg':
            if val not in self.args:
                raise KeyError('Missing argument %r, use --arg' % val)
            return self.args[val]
        elif param == 'entity_local':
            return self.entity_local(val)
        elif param == 'func':
            return self.function_name('sub_' + val)
        else:
            raise KeyError('unknown command argument %s' % param)

class Session:

    def __init__(self, pos, writer, namespace, args={},
                 setup_on_load=False, debug=False, extern=[]):
        self.placer = CommandPlacer(pos)
        self.writer = writer
        self.scope = Scope(namespace, 'etag', {
            'stack_register': 'sr',
            'working_reg': 'a',
            'working_reg_2': 'b',
            'working_reg_3': 'c',
            'success_tracker': 'st',
        }, pos, args, extern)
        self.print_debug = debug
        self.setup_hook = None
        self.setup_on_load = setup_on_load
        self.add_util_command_block()

    def add_util_command_block(self):
        seq = CommandSequence()
        seq.add_block(CommandBlock(Cmd(''), conditional=False, mode='REPEAT'))
        self.add_command_blocks([seq])

        dump = Subsequence()
        dump.add_command(Tellraw([StackPath(None)], Selector('a', None)))
        self.add_subsequence('stack_dump', dump)

    def load_subroutine_table(self, known_functions):
        self.scope.add_function_names(known_functions)

    def add_subsequence(self, name, subsequence):
        commands = list(map(lambda cmd: cmd.resolve(self.scope),
                       subsequence.get_commands()))
        self.writer.write_function(name, commands)
        if self.print_debug:
            print('Function', name)
            for cmd in commands:
                print(' ', cmd)
            print()

    def add_command_blocks(self, lines):
        for line in lines:
            resolved = line.resolve(self.scope)
            self.placer.place(resolved)
            if self.print_debug:
                print('Command block line')
                for (_, cmd), branch in resolved:
                    print(' ', cmd)
                    for (_, cmd2) in branch:
                        print('branch >', cmd2)
                print()

    def add_event_handlers(self, event_handlers):
        tag_events = {
            'minecraft:tick': ('minecraft', 'tick', []),
            'minecraft:load': ('minecraft', 'load', [])
        }
        if self.setup_on_load:
            fn = 'setup_on_load_trampoline'
            self.scope.add_function_names((fn,))
            tag_events['minecraft:load'][2].append(
                self.scope.function_name(fn))
        for event_handler in event_handlers:
            event_name, conditions, handler = (event_handler['event'],
            event_handler['conditions'], event_handler['handler'])
            if event_name in tag_events:
                assert not conditions
                namespace, tag_name, values = tag_events[event_name]
                values.append(self.scope.function_name(handler))
            else:
                self.add_event_handler(event_name, conditions, handler)

        for namespace, tag_name, values in tag_events.values():
            if values:
                self.writer.write_tag('functions', tag_name, values,
                                      namespace=namespace)
                if self.print_debug:
                    print('Tag')
                    print('%s: %s' % (tag_name, values))
                    print()

    def add_event_handler(self, event_name, conditions, handler):
        # TODO refactor
        trampoline = handler + '_trampoline'
        self.scope.add_function_names((trampoline,))
        fn_name = self.scope.function_name(trampoline)
        adv = Advancement('adv_' + handler)
        adv.event_criteria(handler, event_name, conditions)
        adv.reward_function(fn_name)
        self.writer.write_advancement(adv)
        if self.print_debug:
            print('Advancement', adv.name)
            print(adv.to_json())
            print()
        trampoline_seq = Subsequence()
        trampoline_seq.add_command(SimpleResolve('advancement', 'revoke', '@s',
                 'only', self.scope.namespace + ':' + adv.name))
        trampoline_seq.add_command(Function(handler))
        self.add_subsequence(trampoline, trampoline_seq)


    def set_setup_hook(self, hook):
        self.setup_hook = hook

    def extended_setup(self, up, down):
        pass

    def create_up_down_functions(self, pos, setup='setup', cleanup='cleanup'):
        self.scope.add_function_names((setup, cleanup))
        item = '{id:"minecraft:stone",Count:1b,tag:{stack:[],globals:[],working:{int:0}}}'
        nbt = ('{Tags:["%s"],ArmorItems:[%s],NoAI:1b,Invisible:1b,' + \
               'Small:0b,NoGravity:1b,Marker:1b,Invulnerable:1b,' + \
               'NoBasePlate:1b}') % (self.scope.entity_tag, item)
        up = [
            'kill @e[tag=%s]' % self.scope.entity_tag,
            'summon armor_stand %s %s' % (pos, nbt)
        ]
        down = [
            'kill @e[tag=%s]' % self.scope.entity_tag
        ]
        for obj in self.scope.get_objectives():
            up.append('scoreboard objectives add %s dummy' % obj)
            down.append('scoreboard objectives remove %s' % obj)
        for loc in self.scope.get_mem_locs():
            up.append(SetConst(Mem(loc), 0).resolve(self.scope))
        for var, val in {
                'working_reg': 0,
                'success_tracker': 0,
            }.items():
            up.append(SetConst(Var(var), val).resolve(self.scope))
        up.extend(self.placer.output())
        down.extend(self.placer.cleanup())
        self.extended_setup(up, down)
        if self.setup_hook:
            for cmd in self.setup_hook.get_commands():
                up.append(cmd.resolve(self.scope))
        self.writer.write_function(setup, up)
        self.writer.write_function(cleanup, down)
        if self.setup_on_load:
            self.writer.write_function('setup_on_load_trampoline', [
                Function(setup).resolve(self.scope)
            ])
        if self.print_debug:
            print('Function', setup)
            for cmd in up:
                print(' ', cmd)
            print()
            print('Function', cleanup)
            for cmd in down:
                print(' ', cmd)
            print()
        return (Function(setup).resolve(self.scope),
                Function(cleanup).resolve(self.scope))
