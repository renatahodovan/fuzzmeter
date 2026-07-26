'''Extract target blocks from generated Docker Bake configuration.'''


def target_block(bake_hcl: str, target: str) -> str:
    '''Return one complete target block from Bake HCL text.'''
    start = bake_hcl.index(f'target "{target}" {{')
    end = bake_hcl.index('\n}\n', start)
    return bake_hcl[start : end + 3]
