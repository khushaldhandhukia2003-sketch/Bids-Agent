import math

def cylinder_weight(diameter, length, density=7850):

    radius = diameter / 2

    volume = math.pi * radius**2 * length

    weight = volume * density

    return weight