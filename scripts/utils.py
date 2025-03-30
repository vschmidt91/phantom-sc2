import click
import tomllib


def CommandWithConfigFile(config_file_param_name):
    class CustomCommandClass(click.Command):
        def invoke(self, ctx):
            if config_file := ctx.params.get(config_file_param_name):
                config_data = tomllib.load(config_file)
                ctx.params.update(config_data)
            return super().invoke(ctx)

    return CustomCommandClass
